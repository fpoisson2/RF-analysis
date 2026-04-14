"""Module 4b — Merge VdQ + DeepForest + LiDAR MHC trees into one catalog.

Inputs:
  * ``data/vegetation/vdq_arbres_repertories.geojson`` (municipal, has species + DHP)
  * ``data/vegetation/vdq_arbres_remarquables.geojson`` (optional)
  * ``data/vegetation/deepforest_detected.geojson``   (orthophoto detections)
  * LiDAR MHC via backend.terrain.lidar_terrain (canopy height model)

Dedup strategy (per order of authority):
  1. Start with VdQ (highest trust: species + DHP known).
  2. Add DeepForest detections only if >=3m from any existing tree.
  3. Optional LiDAR-driven "blobs" from MHC local maxima, only if >=4m
     from any existing tree. Skipped by default (slow) — pass ``--lidar-maxima``
     to enable.

Outputs:
  * ``data/vegetation/trees_merged.geojson`` — unified FeatureCollection
  * ``data/vegetation/trees_merged.csv``     — lon,lat,h,crown,species,src,conf

Usage:
    python scripts/merge_tree_catalog.py
    python scripts/merge_tree_catalog.py --lidar-maxima
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
VEG = ROOT / "data" / "vegetation"
OUT_GJ = VEG / "trees_merged.geojson"
OUT_CSV = VEG / "trees_merged.csv"


def _load_geojson(p: Path) -> list[dict]:
    if not p.exists():
        print(f"[warn] missing {p.name}, skipping"); return []
    try:
        return json.loads(p.read_text()).get("features", [])
    except Exception as e:
        print(f"[warn] bad geojson {p}: {e}"); return []


def _latlon(f: dict) -> tuple[float, float] | None:
    g = f.get("geometry") or {}
    if g.get("type") != "Point":
        return None
    c = g.get("coordinates") or []
    if len(c) < 2: return None
    return float(c[1]), float(c[0])  # lat, lon


def _kd_index(latlons: np.ndarray):
    """Build a lat/lon KDTree with haversine-ish scaling (good to ~100 km)."""
    from scipy.spatial import cKDTree
    lat = latlons[:, 0]
    lon = latlons[:, 1]
    x = np.radians(lon) * 6378137.0 * np.cos(np.radians(lat.mean()))
    y = np.radians(lat) * 6378137.0
    return cKDTree(np.column_stack([x, y])), lat.mean()


def _to_xy(lat, lon, lat0):
    import numpy as np
    x = np.radians(lon) * 6378137.0 * np.cos(np.radians(lat0))
    y = np.radians(lat) * 6378137.0
    return x, y


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lidar-maxima", action="store_true")
    ap.add_argument("--df-distance", type=float, default=3.0,
                    help="Min dist from existing tree for DeepForest (m)")
    ap.add_argument("--lidar-distance", type=float, default=4.0)
    args = ap.parse_args()

    # --- Layer 1: VdQ municipal trees -----------------------------------------
    vdq = _load_geojson(VEG / "vdq_arbres_repertories.geojson") + \
          _load_geojson(VEG / "vdq_arbres_remarquables.geojson")
    vdq_features = []
    for f in vdq:
        ll = _latlon(f)
        if not ll: continue
        p = f.get("properties") or {}
        # Heuristic height from DHP (breast-height diameter): h ≈ 35 * (1 - exp(-0.02 * DHP_cm))
        # Fallback 10m.
        dhp = (p.get("DIAMETRE") or p.get("dhp") or p.get("DHP")
               or p.get("Dhp_cm") or p.get("diametre"))
        try:
            dhp_cm = float(dhp) if dhp is not None else None
        except (TypeError, ValueError):
            dhp_cm = None
        if dhp_cm and dhp_cm > 0:
            h = 35.0 * (1 - np.exp(-0.02 * dhp_cm))
            crown = max(2.0, 0.8 * np.sqrt(dhp_cm))
        else:
            h = 10.0; crown = 4.0
        species = (p.get("NOM_LATIN") or p.get("NOM_FRANCAIS")
                   or p.get("essence") or p.get("espece") or p.get("nom_fr")
                   or p.get("nom_commun") or "unknown")
        vdq_features.append({
            "lat": ll[0], "lon": ll[1], "h": round(float(h), 1),
            "crown_m": round(float(crown), 1),
            "species": str(species).strip(), "src": "vdq", "conf": 1.0,
        })
    print(f"[vdq] {len(vdq_features)} municipal trees")

    # --- Layer 2: DeepForest detections ---------------------------------------
    df_raw = _load_geojson(VEG / "deepforest_detected.geojson")
    df_ll = []
    for f in df_raw:
        ll = _latlon(f)
        if not ll: continue
        p = f.get("properties") or {}
        df_ll.append({
            "lat": ll[0], "lon": ll[1],
            "h": float(p.get("h") or 0.0),
            "crown_m": float(p.get("crown_m") or 4.0),
            "species": "unknown", "src": "deepforest",
            "conf": float(p.get("score") or 0.5),
        })
    print(f"[df ] {len(df_ll)} DeepForest detections (raw)")

    kept_df = 0
    merged = list(vdq_features)
    if df_ll and merged:
        arr = np.array([(t["lat"], t["lon"]) for t in merged])
        tree, lat0 = _kd_index(arr)
        for t in df_ll:
            x, y = _to_xy(t["lat"], t["lon"], lat0)
            d, _ = tree.query([x, y], k=1)
            if d >= args.df_distance:
                merged.append(t); kept_df += 1
    elif df_ll:
        merged.extend(df_ll); kept_df = len(df_ll)
    print(f"[df ] kept {kept_df} / {len(df_ll)} after dedup (>= {args.df_distance} m)")

    # --- Layer 3: LiDAR local maxima ------------------------------------------
    if args.lidar_maxima:
        try:
            sys.path.insert(0, str(ROOT / "backend"))
            from app.terrain.lidar_terrain import LiDARTerrainManager
            from scipy.ndimage import maximum_filter
            import rasterio

            mgr = LiDARTerrainManager(str(ROOT / "data" / "lidar" / "quebec_city"))
            added = 0
            for mhc in sorted((ROOT / "data" / "lidar" / "quebec_city").glob("MHC_*.tif")):
                print(f"[lid] scanning {mhc.name}")
                with rasterio.open(mhc) as src:
                    data = src.read(1).astype(np.float32)
                    if src.nodata is not None:
                        data[data == src.nodata] = np.nan
                    # 5m local window @ 1m res = window of 5px
                    loc_max = (maximum_filter(data, size=5) == data) & (data >= 3.0)
                    ys, xs = np.where(loc_max)
                    if len(ys) == 0: continue
                    lonlat = [src.xy(int(y), int(x)) for y, x in zip(ys, xs)]
                    # reproject to WGS84
                    if src.crs and src.crs.to_epsg() != 4326:
                        from rasterio.warp import transform as rio_xform
                        xs_src = [p[0] for p in lonlat]; ys_src = [p[1] for p in lonlat]
                        lon_a, lat_a = rio_xform(src.crs, "EPSG:4326", xs_src, ys_src)
                    else:
                        lon_a = [p[0] for p in lonlat]; lat_a = [p[1] for p in lonlat]

                    arr = np.array([(t["lat"], t["lon"]) for t in merged])
                    tree, lat0 = _kd_index(arr)
                    for lat, lon, h in zip(lat_a, lon_a, data[ys, xs]):
                        x, y = _to_xy(lat, lon, lat0)
                        d, _ = tree.query([x, y], k=1)
                        if d >= args.lidar_distance:
                            merged.append({
                                "lat": float(lat), "lon": float(lon),
                                "h": round(float(h), 1), "crown_m": 4.0,
                                "species": "unknown", "src": "lidar", "conf": 0.6,
                            })
                            added += 1
            print(f"[lid] added {added} LiDAR-maxima trees")
        except ImportError as e:
            print(f"[warn] lidar maxima skipped (missing {e})")

    # --- Write outputs --------------------------------------------------------
    feats = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]},
        "properties": {k: v for k, v in t.items() if k not in ("lat", "lon")},
    } for t in merged]
    OUT_GJ.parent.mkdir(parents=True, exist_ok=True)
    OUT_GJ.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lon", "lat", "height_m", "crown_m", "species", "source", "confidence"])
        for t in merged:
            w.writerow([t["lon"], t["lat"], t["h"], t["crown_m"],
                        t["species"], t["src"], t["conf"]])

    print(f"[done] {len(merged)} trees -> {OUT_GJ.name} + {OUT_CSV.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
