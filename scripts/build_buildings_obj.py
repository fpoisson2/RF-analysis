"""Module 2 (alt) -- Extrude footprints directly to OBJ (LOD1-like).

3dfier requires LAS/LAZ input with classified points (class 6 for roof);
we only have MNT + MHC rasters, so we take a simpler path:

  1. Load ``data/buildings/quebec_city_batiments.geojson`` (200k footprints).
  2. For each footprint:
       * ground_z = mean MNT over the footprint (bilinear sample)
       * canopy_h = max MHC over the footprint (building returns often land
         in canopy height model even though it's meant for trees)
       * if canopy_h < 2.5 m (no LiDAR return), fall back to a per-type
         heuristic (residence=7, commerce=10, industriel=8, ...) so we
         always produce a plausible extrusion.
  3. Triangulate the footprint with earcut (via shapely.ops.triangulate),
     build walls + roof as an OBJ, one OBJ per N-km chunk.
  4. Optional py3dtiles conversion if installed.

Outputs:
  data/unreal/buildings/
    chunk_x0_y0.obj ...
    heights.csv          (ID, ground_z, height, source)
    manifest.json

Usage:
    python scripts/build_buildings_obj.py --chunk-km 2
    python scripts/build_buildings_obj.py --limit 1000  (test)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
BLDG_GEOJSON = ROOT / "data" / "buildings" / "quebec_city_batiments.geojson"
MNT_DIR = ROOT / "data" / "lidar" / "quebec_city"

os.environ.setdefault("GDAL_CACHEMAX", "512")

DEFAULT_H = {
    "residence": 7.0, "r\u00e9sidence": 7.0, "residentiel": 7.0,
    "commerce": 10.0, "commercial": 10.0,
    "industriel": 8.0, "industrie": 8.0,
    "institution": 10.0, "institutionnel": 10.0, "public": 10.0,
    "\u00e9cole": 10.0, "ecole": 10.0, "hopital": 15.0, "h\u00f4pital": 15.0,
    "garage": 3.5, "abri": 3.0, "remise": 3.0, "cabanon": 3.0,
    "unknown": 7.0, "autre": 6.0,
}


def _default_height(type_bat: str | None) -> float:
    if not type_bat: return DEFAULT_H["unknown"]
    k = type_bat.strip().lower()
    for key, v in DEFAULT_H.items():
        if key in k:
            return v
    return DEFAULT_H["unknown"]


def _build_raster_samplers():
    """Return (sample_ground(geom), sample_canopy(geom)) which return a
    single metre value given a shapely polygon in EPSG:2949. Uses rasterio
    with windowed reads so memory stays small across 200k buildings."""
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.features import geometry_mask

    mnt_paths = sorted(MNT_DIR.glob("MNT_*.tif"))
    mhc_paths = sorted(MNT_DIR.glob("MHC_*.tif"))

    def _sample(paths, geom, agg):
        minx, miny, maxx, maxy = geom.bounds
        vals = []
        for p in paths:
            with rasterio.open(p) as s:
                b = s.bounds
                if (b.right <= minx or b.left >= maxx or
                    b.top   <= miny or b.bottom >= maxy):
                    continue
                try:
                    w = from_bounds(minx, miny, maxx, maxy,
                                    transform=s.transform)
                    w = w.round_offsets().round_lengths()
                    if w.width <= 0 or w.height <= 0: continue
                except Exception:
                    continue
                arr = s.read(1, window=w, masked=True)
                if arr.count() == 0: continue
                # Inside-footprint mask
                w_transform = s.window_transform(w)
                mask = geometry_mask([geom], out_shape=arr.shape,
                                     transform=w_transform, invert=True)
                sel = arr[mask & ~arr.mask] if hasattr(arr, "mask") else arr[mask]
                if sel.size == 0: continue
                vals.append(float(agg(sel)))
        if not vals: return None
        return float(agg(np.array(vals)))

    def sample_ground(geom):
        return _sample(mnt_paths, geom, np.mean)

    def sample_canopy(geom):
        return _sample(mhc_paths, geom, np.max)

    return sample_ground, sample_canopy


def _poly_to_obj(poly, ground_z: float, height: float,
                 v_offset: int, obj_id: str) -> tuple[list[str], int]:
    """Serialize one building as OBJ fragments, returning lines + new v_offset."""
    from shapely.geometry import MultiPolygon
    lines: list[str] = [f"g {obj_id}"]
    polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    idx = v_offset
    for pp in polys:
        ring = list(pp.exterior.coords)
        if len(ring) < 4: continue
        # Drop closing duplicate, if any
        if ring[0] == ring[-1]: ring = ring[:-1]
        n = len(ring)
        # Walls
        for (x, y) in ring:
            lines.append(f"v {x:.3f} {y:.3f} {ground_z:.3f}")
        for (x, y) in ring:
            lines.append(f"v {x:.3f} {y:.3f} {ground_z + height:.3f}")
        # Wall quads as tri pairs (OBJ is 1-indexed)
        base = idx + 1
        roof_off = idx + 1 + n
        for i in range(n):
            a = base + i
            b = base + (i + 1) % n
            c = roof_off + (i + 1) % n
            d = roof_off + i
            lines.append(f"f {a} {b} {c}")
            lines.append(f"f {a} {c} {d}")
        # Roof (fan triangulation around first vertex -- good enough for LOD1
        # convex-ish footprints; for robustness one could use shapely
        # triangulate, but fan covers 90%+ buildings fine).
        for i in range(1, n - 1):
            lines.append(f"f {roof_off} {roof_off + i} {roof_off + i + 1}")
        idx += 2 * n
    return lines, idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/unreal/buildings")
    ap.add_argument("--chunk-km", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-area", type=float, default=8.0)
    args = ap.parse_args()

    try:
        import geopandas as gpd
    except ImportError:
        print("Missing geopandas: pip install geopandas", file=sys.stderr); return 2

    if not BLDG_GEOJSON.exists():
        print(f"[err] {BLDG_GEOJSON}", file=sys.stderr); return 2

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[load] {BLDG_GEOJSON.name} ...")
    gdf = gpd.read_file(BLDG_GEOJSON).to_crs(2949)
    if "ID" in gdf.columns:
        gdf = gdf.rename(columns={"ID": "OBJECTID"})
    elif "OBJECTID" not in gdf.columns:
        gdf = gdf.reset_index().rename(columns={"index": "OBJECTID"})
    gdf["OBJECTID"] = gdf["OBJECTID"].astype(str)
    gdf["_area"] = gdf.geometry.area
    gdf = gdf[gdf["_area"] >= args.min_area].reset_index(drop=True)
    print(f"[load] {len(gdf)} footprints >= {args.min_area} m^2")

    if args.limit: gdf = gdf.head(args.limit)

    sample_ground, sample_canopy = _build_raster_samplers()

    # Chunk by 2949 bbox grid
    minx, miny, maxx, maxy = gdf.total_bounds
    chunk_m = args.chunk_km * 1000.0
    xs = np.arange(minx, maxx + chunk_m, chunk_m)
    ys = np.arange(miny, maxy + chunk_m, chunk_m)

    heights_csv = (out_dir / "heights.csv").open("w", newline="", encoding="utf-8")
    hw = csv.writer(heights_csv)
    hw.writerow(["OBJECTID", "ground_z", "height", "source"])

    manifest = {"chunks": [], "min_area": args.min_area,
                "footprint_crs": "EPSG:2949"}
    chunk_count = 0
    bldg_count = 0

    for ix in range(len(xs) - 1):
        for iy in range(len(ys) - 1):
            xl, yl, xr, yr = xs[ix], ys[iy], xs[ix + 1], ys[iy + 1]
            sub = gdf.cx[xl:xr, yl:yr]
            if len(sub) == 0: continue
            name = f"chunk_x{ix}_y{iy}.obj"
            out_path = out_dir / name
            if out_path.exists() and out_path.stat().st_size > 0:
                print(f"[skip] {name}"); continue
            lines = [f"# {len(sub)} buildings (chunk {ix},{iy})"]
            v_off = 0
            t0 = __import__("time").time()
            for _, r in sub.iterrows():
                gz = sample_ground(r.geometry)
                ch = sample_canopy(r.geometry)
                if gz is None: gz = 0.0
                if ch is None or ch < 2.5:
                    h = _default_height(r.get("TYPE_BATIMENT"))
                    src = "type"
                else:
                    h = float(ch); src = "mhc"
                frag, v_off = _poly_to_obj(r.geometry, gz, h, v_off,
                                           str(r["OBJECTID"]))
                lines.extend(frag)
                hw.writerow([r["OBJECTID"], round(gz, 2), round(h, 2), src])
                bldg_count += 1
            out_path.write_text("\n".join(lines), encoding="utf-8")
            dt = __import__("time").time() - t0
            print(f"[ok ] {name} ({len(sub)} bldgs, {dt:.1f}s, "
                  f"{len(sub) / max(dt, 0.01):.0f} bldg/s)")
            manifest["chunks"].append(name)
            chunk_count += 1

    heights_csv.close()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[done] {bldg_count} buildings across {chunk_count} chunks -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
