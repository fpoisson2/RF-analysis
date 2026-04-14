"""Detect individual trees in CMQ 2021 orthophotos with DeepForest and
write a GeoJSON that the backend merges into its tree catalog.

Usage:
    python scripts/run_deepforest.py path/to/tile1.tif [path/to/tile2.tif ...]

For each orthophoto:
  1. Slice into patches and run the DeepForest GPU model.
  2. Georeference the bounding boxes using the raster affine transform.
  3. Sample height from the corresponding LiDAR MHC GeoTIFFs in
     data/lidar/quebec_city/ (the existing MNT/MHC pyramid).
  4. Write detections to data/vegetation/deepforest_detected.geojson
     (merging with any previous run).

The detections are treated as an extra source by backend/app/vegetation/
deepforest_trees.py (see module doc). Dedup against VdQ + LiDAR happens
when the backend merges.

Requirements:
    pip install deepforest rasterio torch shapely
    (torch must be the CUDA build for the RTX 5070 Ti to be used)
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "vegetation" / "deepforest_detected.geojson"
LIDAR_DIR = ROOT / "data" / "lidar" / "quebec_city"


def _load_existing() -> dict:
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"type": "FeatureCollection", "features": []}


def _save(fc: dict) -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(fc, f)


def _run_one(tif_path: Path, model, mhc_sampler) -> list[dict]:
    import rasterio
    from rasterio.transform import xy
    from rasterio.warp import transform as rio_transform

    print(f"[run] {tif_path.name}")
    boxes = model.predict_tile(
        path=str(tif_path),
        patch_size=400, patch_overlap=0.05, iou_threshold=0.15,
    )
    if boxes is None or len(boxes) == 0:
        print("  (no detections)")
        return []

    with rasterio.open(tif_path) as src:
        transform = src.transform
        crs = src.crs

    # Pixel bbox → source-CRS bbox → WGS84 centroid
    centroids_x_src, centroids_y_src, widths_m = [], [], []
    for _, r in boxes.iterrows():
        x1, y1 = xy(transform, r["ymin"], r["xmin"], offset="ul")
        x2, y2 = xy(transform, r["ymax"], r["xmax"], offset="ul")
        centroids_x_src.append((x1 + x2) / 2.0)
        centroids_y_src.append((y1 + y2) / 2.0)
        widths_m.append(abs(x2 - x1))

    if crs is not None and crs.to_epsg() != 4326:
        lon_arr, lat_arr = rio_transform(crs, "EPSG:4326",
                                         centroids_x_src, centroids_y_src)
    else:
        lon_arr, lat_arr = centroids_x_src, centroids_y_src

    out: list[dict] = []
    for lon, lat, w, (_, r) in zip(lon_arr, lat_arr, widths_m, boxes.iterrows()):
        h = mhc_sampler(lat, lon)
        if h is None or h < 2.5:
            continue
        out.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {
                "h": round(float(h), 1),
                "src": "deepforest",
                "score": float(r["score"]),
                "crown_m": round(float(w), 2),
            },
        })
    print(f"  -> {len(out)} trees (of {len(boxes)} detections, filtered by MHC)")
    return out


def _build_mhc_sampler():
    """Return a function sample(lat, lon) -> max MHC value in a 0.5 m window,
    or None. Uses the LiDARTerrainManager so we get the existing GeoTIFF
    pyramid already indexed by the backend."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.terrain.lidar_terrain import LiDARTerrainManager

    mgr = LiDARTerrainManager(str(LIDAR_DIR))

    def sample(lat: float, lon: float):
        try:
            # Elevation with canopy = MNT + MHC; subtract bare earth to get
            # canopy height at this point.
            with_canopy = mgr.get_elevation(lat, lon, use_canopy=True)
            ground = mgr.get_elevation(lat, lon, use_canopy=False)
            if with_canopy is None or ground is None:
                return None
            h = float(with_canopy) - float(ground)
            return h if h > 0 else None
        except Exception:
            return None

    return sample


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tifs", nargs="+", help="CMQ orthophoto GeoTIFF(s)")
    ap.add_argument("--no-gpu", action="store_true")
    args = ap.parse_args()

    try:
        from deepforest import main as df_main
        import torch
    except ImportError as e:
        print(f"Missing dependency: {e}\n"
              "  pip install deepforest torch rasterio", file=sys.stderr)
        return 2

    model = df_main.deepforest()
    # DeepForest 2.x: model is loaded automatically from HF on construction.
    # For older versions, fall back to use_release().
    if hasattr(model, "use_release"):
        model.use_release()
    elif hasattr(model, "load_model"):
        try: model.load_model(model_name="weecology/deepforest-tree")
        except Exception: pass  # default constructor already loaded it
    if not args.no_gpu and torch.cuda.is_available():
        model.to(torch.device("cuda"))
        print(f"[gpu] using {torch.cuda.get_device_name(0)}")
    else:
        print("[cpu] running without CUDA")

    sampler = _build_mhc_sampler()
    fc = _load_existing()
    for tif in args.tifs:
        p = Path(tif)
        if not p.exists():
            print(f"[skip] not found: {p}", file=sys.stderr)
            continue
        fc["features"].extend(_run_one(p, model, sampler))

    _save(fc)
    print(f"[done] {len(fc['features'])} total features -> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
