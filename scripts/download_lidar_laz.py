"""Download classified LAZ tiles from the MRNF LiDAR Quebec index.

Reads ``E:\\rf_analysis\\lidar_laz\\Index_Lidar.gpkg`` (tile index GPKG
downloaded from https://diffusion.mern.gouv.qc.ca/.../Index_lidar_GPKG.zip)
and pulls every tile whose footprint intersects a user-provided bbox.

By default, selects tiles with classification class 6 (buildings) present,
preferring the most recent session where multiple cover the same tile.

Total Quebec-City-area raw LAZ is typically a few hundred tiles at ~15 MB
each -> a few GB. Downloads to ``--out`` with resume + parallel workers.

Usage:
    python scripts/download_lidar_laz.py --lat 46.8139 --lon -71.2080 --km 10
    python scripts/download_lidar_laz.py --km 15 --workers 6
    python scripts/download_lidar_laz.py --require-class 6 --out E:/rf_analysis/lidar_laz/tiles
"""
from __future__ import annotations

import argparse
import concurrent.futures
import math
import sys
import time
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = Path("E:/rf_analysis/lidar_laz/Index_Lidar.gpkg")
DEFAULT_OUT = Path("E:/rf_analysis/lidar_laz/tiles")


def _fmt_bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024: return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def _download(row, out_dir: Path, retries: int = 4) -> tuple[str, int]:
    """Returns (name, status): 0 ok, 1 skip, 2 fail.

    Uses curl for the actual HTTP (more reliable than urllib against the
    MRNF server, which tears down persistent connections on 8+ parallelism)
    with automatic resume, retry, and backoff.
    """
    import subprocess
    url = row["TELECHARGEMENT_TUILE"]
    if not url or not url.lower().endswith(".laz"):
        return (row.get("NOM_TUILE", "?"), 2)
    name = url.rsplit("/", 1)[-1]
    dst = out_dir / name
    expected_mb = float(row.get("TAILLE_MO") or 0)
    min_bytes = max(500_000, int(expected_mb * 0.8 * 1_000_000))
    if dst.exists() and dst.stat().st_size >= min_bytes:
        return (name, 1)
    for attempt in range(retries):
        cmd = ["curl", "-L", "-s", "-S", "-C", "-",
               "-A", "Mozilla/5.0",
               "--retry", "3", "--retry-delay", "2",
               "--connect-timeout", "30",
               "--max-time", "900",
               "-o", str(dst), url.strip()]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and dst.exists() and dst.stat().st_size >= min_bytes:
            return (name, 0)
        if attempt < retries - 1:
            time.sleep(2 + attempt * 3)
    try:
        if dst.exists() and dst.stat().st_size < min_bytes:
            dst.unlink()
    except Exception: pass
    return (name, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(DEFAULT_INDEX))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--lat", type=float, default=46.8139)
    ap.add_argument("--lon", type=float, default=-71.2080)
    ap.add_argument("--km", type=float, default=10.0, help="Half-size of square bbox")
    ap.add_argument("--workers", type=int, default=2,
                    help="MRNF server drops connections above ~3 parallel")
    ap.add_argument("--require-class", type=str, default="",
                    help="Only keep tiles whose CLASSIFICATION string contains "
                         "this code (e.g. '6' for buildings).")
    ap.add_argument("--latest-only", action="store_true",
                    help="If multiple tiles overlap, keep only newest DATE_INDEX")
    ap.add_argument("--max-tiles", type=int, default=0,
                    help="Cap download count (0 = unlimited)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    idx = Path(args.index)
    if not idx.exists():
        print(f"[err] Missing index {idx}. Get it from "
              "https://diffusion.mern.gouv.qc.ca/diffusion/RGQ/Lidar/_Index/"
              "Index_lidar_GPKG.zip", file=sys.stderr); return 2

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)

    import geopandas as gpd
    from shapely.geometry import box

    print(f"[load] {idx.name} ({_fmt_bytes(idx.stat().st_size)})...")
    gdf = gpd.read_file(idx, layer="Index_Tuiles_LiDAR")
    if gdf.crs is None: gdf = gdf.set_crs(4617, allow_override=True)
    print(f"[load] {len(gdf):,} total tiles  crs={gdf.crs}")

    # Bbox selection in the index CRS
    dlat = args.km / 111.32
    dlon = args.km / (111.32 * math.cos(math.radians(args.lat)))
    bbox = box(args.lon - dlon, args.lat - dlat,
               args.lon + dlon, args.lat + dlat)
    bbox_gdf = gpd.GeoDataFrame(geometry=[bbox], crs=4326).to_crs(gdf.crs)
    hits = gdf[gdf.intersects(bbox_gdf.unary_union)].copy()
    print(f"[bbox] {len(hits)} tiles intersect {args.km} km bbox "
          f"around ({args.lat},{args.lon})")

    if args.require_class:
        hits = hits[hits["CLASSIFICATION"].fillna("")
                    .str.split(",").apply(lambda xs: args.require_class in
                                         [x.strip() for x in xs])]
        print(f"[filt] class '{args.require_class}' present -> {len(hits)}")

    if args.latest_only and len(hits) > 0:
        hits["DATE_INDEX"] = hits["DATE_INDEX"].astype(str)
        hits = hits.sort_values("DATE_INDEX", ascending=False)
        hits = hits.drop_duplicates(subset=["NOM_TUILE"], keep="first")
        print(f"[filt] latest-only -> {len(hits)}")

    if args.max_tiles:
        hits = hits.head(args.max_tiles)
        print(f"[filt] cap -> {len(hits)}")

    total_mb = hits["TAILLE_MO"].fillna(0).astype(float).sum()
    print(f"[plan] {len(hits)} tiles, ~{total_mb / 1024:.1f} GB total")

    if args.dry_run:
        for _, r in hits.head(20).iterrows():
            print(f"  {r['NOM_TUILE']:30s}  {r.get('DATES_ACQUISITION')}  "
                  f"cls={r.get('CLASSIFICATION')}  {r.get('TAILLE_MO')} MB")
        if len(hits) > 20: print(f"  ... (+{len(hits) - 20} more)")
        return 0

    n_ok = n_skip = n_fail = 0
    t0 = time.time()
    rows = hits.to_dict("records")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_download, r, out_dir): r for r in rows}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            name, status = fut.result()
            if status == 0: n_ok += 1; tag = "get "
            elif status == 1: n_skip += 1; tag = "skip"
            else: n_fail += 1; tag = "FAIL"
            print(f"[{tag}] {i:>5}/{len(rows)}  {name}")

    dt = time.time() - t0
    print(f"[done] ok={n_ok} skip={n_skip} fail={n_fail}  "
          f"in {dt / 60:.1f} min  -> {out_dir}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
