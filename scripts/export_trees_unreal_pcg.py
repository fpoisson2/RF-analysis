"""Module 4c — Export merged tree catalog as Unreal PCG-ready CSVs.

Reads ``data/vegetation/trees_merged.csv`` and writes per-species CSVs with
Unreal-friendly columns (X, Y, Z in centimetres, relative to a local origin
you can snap the landscape to), bucketed by height quintile so that PCG
Graph can pick the right mesh LOD variant.

Output directory (default ``data/unreal/trees/``):
  ├── origin.json            # lat/lon/UTM of world (0,0)
  ├── _manifest.json         # list of per-species CSVs with counts
  ├── acer_saccharinum.csv
  ├── picea_glauca.csv
  ├── …
  └── unknown_LOD2.csv       # 2D billboard fallback bucket

CSV columns: Name,Location_X,Location_Y,Location_Z,Scale,Rotation_Yaw,Variant

Usage:
    python scripts/export_trees_unreal_pcg.py \
        --origin-lat 46.8139 --origin-lon -71.2080
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "data" / "vegetation" / "trees_merged.csv"


def _slug(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin-lat", type=float, default=46.8139)
    ap.add_argument("--origin-lon", type=float, default=-71.2080)
    ap.add_argument("--out", default="data/unreal/trees")
    ap.add_argument("--z-exaggeration", type=float, default=1.5,
                    help="Match CesiumJS vertical exaggeration for consistency")
    args = ap.parse_args()

    if not IN_CSV.exists():
        print(f"[err] run merge_tree_catalog.py first ({IN_CSV})",
              file=sys.stderr); return 2

    try:
        from pyproj import Transformer
    except ImportError:
        print("Missing pyproj: pip install pyproj", file=sys.stderr); return 2

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    # WGS84 → UTM18N (metres)
    t84_to_utm = Transformer.from_crs(4326, 32618, always_xy=True)
    ox, oy = t84_to_utm.transform(args.origin_lon, args.origin_lat)

    (out_dir / "origin.json").write_text(json.dumps({
        "lat": args.origin_lat, "lon": args.origin_lon,
        "utm_x_m": ox, "utm_y_m": oy, "crs": "EPSG:32618",
        "unreal_unit_cm": 1.0,
    }, indent=2))

    by_species: dict[str, list[list]] = defaultdict(list)
    total = 0
    import hashlib
    with IN_CSV.open(encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            lon = float(row["lon"]); lat = float(row["lat"])
            h = float(row["height_m"]); crown = float(row["crown_m"])
            sp = _slug(row["species"])
            # bucket by height quintile for LOD variants
            if h < 6: bucket = "s"
            elif h < 12: bucket = "m"
            elif h < 20: bucket = "l"
            else: bucket = "xl"
            key = f"{sp}_{bucket}"
            x, y = t84_to_utm.transform(lon, lat)
            # Local Unreal coords: origin at (ox, oy), Y axis flipped (UE is LH)
            ux = (x - ox) * 100.0   # cm
            uy = -(y - oy) * 100.0  # cm (flip)
            uz = 0.0
            scale = max(0.3, h / 10.0)
            # Deterministic rotation variant — consistent between runs
            hh = int(hashlib.md5(f"{lon:.6f}_{lat:.6f}".encode()).hexdigest()[:6], 16)
            yaw = (hh % 360)
            variant = hh % 8  # 0-7 mesh variant index
            by_species[key].append([f"t{total}", round(ux, 1), round(uy, 1),
                                    round(uz, 1), round(scale, 3), yaw, variant])
            total += 1

    manifest = {"total": total, "z_exaggeration": args.z_exaggeration, "files": []}
    for key, rows in sorted(by_species.items(), key=lambda kv: -len(kv[1])):
        name = f"{key}.csv"
        with (out_dir / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Name", "Location_X", "Location_Y", "Location_Z",
                        "Scale", "Rotation_Yaw", "Variant"])
            w.writerows(rows)
        manifest["files"].append({"key": key, "count": len(rows), "file": name})
        print(f"  [w] {name:40s}  {len(rows):>7} trees")

    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[done] {total} trees across {len(by_species)} species/bucket → {out_dir}")
    print("\nUnreal import:")
    print("  1. DataTable-import each CSV into /Game/PCG/Trees/DT_<species>")
    print("  2. In your PCG Graph, add a 'Get Points From DataTable' for each DT")
    print("  3. Use 'Variant' to pick a static mesh from a mesh array per species")
    return 0


if __name__ == "__main__":
    sys.exit(main())
