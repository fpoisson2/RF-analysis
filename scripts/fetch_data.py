"""Fetch data assets required by the RF analysis backend.

Two sources are supported:

  1. --from-backup <path>   Copy/symlink from a local backup directory
                            (layout: <path>/lidar/quebec_city/*.tif,
                                     <path>/buildings_vdq/vdq-batiments.geojson)

  2. --from-release          Download buildings GeoJSON from the GitHub Release
                             attached to this repo. LiDAR tiles are NOT hosted
                             on GitHub (~13 GB total) and must be obtained from
                             MERN Québec "Forêt ouverte" or a local backup.

Targets:
    data/buildings/quebec_city_batiments.geojson   (~165 MB)
    data/lidar/quebec_city/{MNT,MHC}_21L1{3,4}{NE,NO,SE,SO}.tif  (~13 GB)
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

BUILDINGS_DST = DATA / "buildings" / "quebec_city_batiments.geojson"
LIDAR_DST = DATA / "lidar" / "quebec_city"

LIDAR_TILES = [
    f"{kind}_21L{sheet}{quad}.tif"
    for kind in ("MNT", "MHC")
    for sheet in ("13", "14")
    for quad in ("NE", "NO", "SE", "SO")
]

# GitHub Release tag hosting the compressed buildings GeoJSON.
# Create with:  gh release create data-v1 data/buildings/quebec_city_batiments.geojson.gz
RELEASE_TAG = "data-v1"
RELEASE_REPO = "francispg/RF-analysis"  # adjust if fork
BUILDINGS_URL = (
    f"https://github.com/{RELEASE_REPO}/releases/download/{RELEASE_TAG}/"
    "quebec_city_batiments.geojson.gz"
)


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src, dst)
        print(f"  symlinked  {dst.relative_to(ROOT)} -> {src}")
    except (OSError, NotImplementedError):
        shutil.copy2(src, dst)
        print(f"  copied     {dst.relative_to(ROOT)}")


def from_backup(backup: Path) -> None:
    bld = backup / "buildings_vdq" / "vdq-batiments.geojson"
    if bld.is_file():
        _link_or_copy(bld, BUILDINGS_DST)
    else:
        print(f"  MISSING   {bld}")

    lidar_src = backup / "lidar" / "quebec_city"
    if not lidar_src.is_dir():
        print(f"  MISSING   {lidar_src}")
        return
    for name in LIDAR_TILES:
        src = lidar_src / name
        if src.is_file():
            _link_or_copy(src, LIDAR_DST / name)
        else:
            print(f"  MISSING   {src}")


def _download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)


def from_release() -> None:
    gz = BUILDINGS_DST.with_suffix(BUILDINGS_DST.suffix + ".gz")
    _download(BUILDINGS_URL, gz)
    print(f"  gunzip -> {BUILDINGS_DST.relative_to(ROOT)}")
    with gzip.open(gz, "rb") as src, open(BUILDINGS_DST, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1 << 20)
    gz.unlink()
    print(
        "\nLiDAR tiles are not hosted on GitHub (~13 GB). Obtain from:\n"
        "  https://www.foretouverte.gouv.qc.ca/  (MNT + MHC, feuillets 21L13/21L14)\n"
        f"and place as:  {LIDAR_DST.relative_to(ROOT)}/{{MNT,MHC}}_21L1{{3,4}}{{NE,NO,SE,SO}}.tif"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-backup", type=Path, metavar="PATH",
                   help="Local backup directory (e.g. E:/rf_analysis/data_backup)")
    g.add_argument("--from-release", action="store_true",
                   help="Download buildings GeoJSON from GitHub Release")
    args = p.parse_args()

    if args.from_backup:
        if not args.from_backup.is_dir():
            print(f"error: {args.from_backup} is not a directory", file=sys.stderr)
            return 2
        from_backup(args.from_backup)
    else:
        from_release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
