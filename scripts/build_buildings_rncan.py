"""Extrude RNCan auto-building footprints (with heightmin/max + elevmin/max)
to LOD1 OBJ chunks. Much faster than 3dfier because heights are already
baked into the RNCan attributes (LiDAR-derived, 2017).

Input: ``E:/rf_analysis/data_backup/buildings_rncan/<tile>.gpkg`` (one or
many GPKG files from NRCan automatic extraction dataset).

Output: ``data/unreal/buildings_rncan/chunk_x{ix}_y{iy}.obj`` + heights CSV.

Height rule:
  ground_z = elevmin
  roof_z   = elevmin + heightmax

Usage:
    python scripts/build_buildings_rncan.py --chunk-km 2
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RNCAN_DIR = Path("E:/rf_analysis/data_backup/buildings_rncan")


def _poly_to_obj(poly, gz, roof_z, v_offset, obj_id):
    lines = [f"g {obj_id}"]
    polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    idx = v_offset
    for pp in polys:
        ring = list(pp.exterior.coords)
        if len(ring) < 4: continue
        if ring[0] == ring[-1]: ring = ring[:-1]
        n = len(ring)
        for (x, y) in ring:
            lines.append(f"v {x:.3f} {y:.3f} {gz:.3f}")
        for (x, y) in ring:
            lines.append(f"v {x:.3f} {y:.3f} {roof_z:.3f}")
        base = idx + 1; roof_off = idx + 1 + n
        for i in range(n):
            a = base + i
            b = base + (i + 1) % n
            c = roof_off + (i + 1) % n
            d = roof_off + i
            lines.append(f"f {a} {b} {c}")
            lines.append(f"f {a} {c} {d}")
        for i in range(1, n - 1):
            lines.append(f"f {roof_off} {roof_off + i} {roof_off + i + 1}")
        idx += 2 * n
    return lines, idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in-dir", default=str(RNCAN_DIR))
    ap.add_argument("--out", default="data/unreal/buildings_rncan")
    ap.add_argument("--chunk-km", type=float, default=2.0)
    ap.add_argument("--min-height", type=float, default=2.0,
                    help="Skip buildings shorter than this (noise/artifacts)")
    args = ap.parse_args()

    try:
        import geopandas as gpd
        import pandas as pd
    except ImportError as e:
        print(f"Missing: {e}", file=sys.stderr); return 2

    in_dir = Path(args.in_dir)
    gpkgs = list(in_dir.rglob("*.gpkg"))
    if not gpkgs:
        print(f"[err] no .gpkg in {in_dir}", file=sys.stderr); return 2
    print(f"[load] {len(gpkgs)} GPKG files...")

    parts = []
    for p in gpkgs:
        g = gpd.read_file(p)
        parts.append(g)
        print(f"  {p.name}: {len(g)}")
    gdf = pd.concat(parts, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=parts[0].crs)
    print(f"[load] {len(gdf)} total RNCan buildings")

    # Project to EPSG:2949 (matches our MNT, native metric)
    gdf = gdf.to_crs(2949)

    # Filter low/invalid
    gdf = gdf[(gdf["heightmax"].fillna(0) >= args.min_height) &
              (gdf["elevmin"].notna())].reset_index(drop=True)
    print(f"[filt] {len(gdf)} after min_height={args.min_height} + valid elev")

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    minx, miny, maxx, maxy = gdf.total_bounds
    chunk_m = args.chunk_km * 1000.0
    xs = np.arange(minx, maxx + chunk_m, chunk_m)
    ys = np.arange(miny, maxy + chunk_m, chunk_m)

    heights_csv = (out_dir / "heights.csv").open("w", newline="", encoding="utf-8")
    hw = csv.writer(heights_csv)
    hw.writerow(["feature_id", "ground_z", "height_m", "area_m2",
                 "quality", "datemax"])

    manifest = {"chunks": [], "crs": "EPSG:2949",
                "source": "NRCan auto-building 2017"}
    total = 0
    t0 = time.time()
    for ix in range(len(xs) - 1):
        for iy in range(len(ys) - 1):
            xl, yl, xr, yr = xs[ix], ys[iy], xs[ix + 1], ys[iy + 1]
            sub = gdf.cx[xl:xr, yl:yr]
            if len(sub) == 0: continue
            name = f"chunk_x{ix}_y{iy}.obj"
            out_path = out_dir / name
            if out_path.exists() and out_path.stat().st_size > 0:
                continue
            lines = [f"# {len(sub)} RNCan buildings (chunk {ix},{iy})"]
            v_off = 0
            for _, r in sub.iterrows():
                gz = float(r["elevmin"])
                h = float(r["heightmax"])
                roof_z = gz + h
                frag, v_off = _poly_to_obj(r.geometry, gz, roof_z, v_off,
                                           str(r["feature_id"])[:8])
                lines.extend(frag)
                hw.writerow([r["feature_id"], round(gz, 2), round(h, 2),
                             round(float(r.get("bldgarea") or 0), 1),
                             r.get("qltylvl_en"), r.get("datemax")])
                total += 1
            out_path.write_text("\n".join(lines), encoding="utf-8")
            manifest["chunks"].append(name)
            print(f"[ok ] {name} ({len(sub)} bldgs)")

    heights_csv.close()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    dt = time.time() - t0
    print(f"[done] {total} buildings in {len(manifest['chunks'])} chunks in "
          f"{dt:.1f}s -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
