"""Download CMQ 2021 orthophoto tiles (1km x 1km GeoTIFF @12cm) within a
geographic bbox around a point. Each tile is ~200 MB.

Prereq: `scripts/download_data.py` has already fetched the tile index SHP.

Usage:
    python scripts/download_ortho_tiles.py --lat 46.813 --lon -71.208 --km 1.5
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "vegetation" / "ortho_tiles"
INDEX_SHP = (ROOT / "data" / "vegetation" / "cmq_tile_index"
             / "INDEX_IMAGERIE_CMQ" / "INDEX_IMAGERIE_CMQ.shp")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--km", type=float, default=1.5,
                    help="Half-width of the bbox in km (default 1.5 → 9 tiles)")
    ap.add_argument("--max-tiles", type=int, default=25)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import math
    import subprocess
    import geopandas as gpd
    from shapely.geometry import box

    if not INDEX_SHP.exists():
        print(f"Tile index missing: {INDEX_SHP}\nRun scripts/download_data.py first.",
              file=sys.stderr)
        return 2

    gdf = gpd.read_file(INDEX_SHP).to_crs(4326)
    dlat = args.km / 111.32
    dlon = args.km / (111.32 * max(math.cos(math.radians(args.lat)), 0.2))
    bbox = box(args.lon - dlon, args.lat - dlat,
               args.lon + dlon, args.lat + dlat)
    hits = gdf[gdf.intersects(bbox) &
               gdf["NOM_IMAGE"].str.startswith("2021_CMQ_", na=False)].copy()
    # Sort by distance to centre so the closest tiles download first
    centre = ((args.lon - dlon + args.lon + dlon) / 2,
              (args.lat - dlat + args.lat + dlat) / 2)
    hits["_d"] = hits.geometry.centroid.apply(
        lambda p: (p.x - centre[0]) ** 2 + (p.y - centre[1]) ** 2
    )
    hits = hits.sort_values("_d").head(args.max_tiles)

    print(f"{len(hits)} tiles within {args.km} km of ({args.lat}, {args.lon}). "
          f"Est. total: {len(hits) * 200:.0f} MB.")
    OUT.mkdir(parents=True, exist_ok=True)

    ok = skip = err = 0
    for _, r in hits.iterrows():
        name = r["NOM_IMAGE"] + ".tif"
        url = r["URLGEOTIFF"]
        if not url or url.strip().lower() == "none":
            continue
        dest = OUT / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            print(f"[skip] {name} ({dest.stat().st_size / 1e6:.0f} MB)")
            skip += 1
            continue
        if args.dry_run:
            print(f"[dry ] {name}  <- {url}")
            continue
        print(f"[get ] {name}")
        cmd = ["curl", "-L", "-C", "-", "-A", "Mozilla/5.0",
               "--retry", "5", "--retry-delay", "3",
               "-o", str(dest), url.strip()]
        result = subprocess.run(cmd)
        if result.returncode == 0 and dest.exists() and dest.stat().st_size > 1_000_000:
            ok += 1
        else:
            err += 1
            print(f"  -> FAIL (rc={result.returncode})", file=sys.stderr)

    print(f"\nDone. ok={ok} skip={skip} err={err}  ->  {OUT}")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
