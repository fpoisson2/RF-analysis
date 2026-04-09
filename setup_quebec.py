#!/usr/bin/env python3
"""
Setup script - Downloads terrain data for Quebec province.

Usage:
    python setup_quebec.py              # Download essential Quebec tiles
    python setup_quebec.py --full       # Download all Quebec tiles
    python setup_quebec.py --montreal   # Montreal area only
    python setup_quebec.py --quebec-city # Quebec City area only

Data sources:
    - SRTM 30m elevation tiles (NASA/USGS)
    - Microsoft Building Footprints for Quebec
"""
import os
import sys
import gzip
import math
import argparse
import logging
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
SRTM_DIR = DATA_DIR / "srtm"
SRTM_DIR.mkdir(parents=True, exist_ok=True)

# Quebec regions with their SRTM tile coordinates
REGIONS = {
    "montreal": {
        "description": "Grand Montréal",
        "tiles": [(45, -74), (45, -73), (45, -72), (44, -74), (44, -73)],
    },
    "quebec_city": {
        "description": "Région de Québec",
        "tiles": [(46, -72), (46, -71), (46, -70), (47, -71), (47, -72)],
    },
    "trois_rivieres": {
        "description": "Mauricie / Trois-Rivières",
        "tiles": [(46, -73), (46, -72)],
    },
    "sherbrooke": {
        "description": "Estrie / Sherbrooke",
        "tiles": [(45, -72), (45, -71), (45, -70)],
    },
    "gatineau": {
        "description": "Outaouais / Gatineau",
        "tiles": [(45, -76), (45, -75), (46, -76), (46, -75)],
    },
    "saguenay": {
        "description": "Saguenay-Lac-Saint-Jean",
        "tiles": [(48, -72), (48, -71), (48, -70), (47, -72), (47, -71)],
    },
    "rimouski": {
        "description": "Bas-Saint-Laurent",
        "tiles": [(48, -69), (48, -68), (47, -69), (47, -68)],
    },
    "laurentides": {
        "description": "Laurentides",
        "tiles": [(46, -74), (46, -75), (47, -74), (47, -75)],
    },
}


def srtm_tile_name(lat: int, lon: int) -> str:
    """Generate SRTM tile filename."""
    lat_prefix = "N" if lat >= 0 else "S"
    lon_prefix = "E" if lon >= 0 else "W"
    return f"{lat_prefix}{abs(lat):02d}{lon_prefix}{abs(lon):03d}"


def download_srtm_tile(lat: int, lon: int) -> bool:
    """Download a single SRTM tile. Returns True if successful."""
    name = srtm_tile_name(lat, lon)
    hgt_path = SRTM_DIR / f"{name}.hgt"

    if hgt_path.exists():
        size = hgt_path.stat().st_size
        expected_1 = 3601 * 3601 * 2  # 1-arc-second
        expected_3 = 1201 * 1201 * 2  # 3-arc-second
        if size in (expected_1, expected_3):
            logger.info(f"  {name}.hgt already exists ({size:,} bytes)")
            return True

    # Try AWS terrain tiles (most reliable, no auth)
    url = f"https://elevation-tiles-prod.s3.amazonaws.com/skadi/{name[:3]}/{name}.hgt.gz"

    try:
        logger.info(f"  Downloading {name}.hgt from AWS...")
        req = Request(url, headers={"User-Agent": "RF-Planner-Setup/1.0"})
        response = urlopen(req, timeout=60)
        compressed = response.read()
        data = gzip.decompress(compressed)

        with open(hgt_path, "wb") as f:
            f.write(data)

        logger.info(f"  OK: {name}.hgt ({len(data):,} bytes)")
        return True
    except HTTPError as e:
        if e.code == 404:
            logger.warning(f"  Tile {name} not available (ocean/no data)")
        else:
            logger.error(f"  HTTP error for {name}: {e}")
    except Exception as e:
        logger.error(f"  Failed to download {name}: {e}")

    return False


def download_region(region_name: str) -> tuple[int, int]:
    """Download all tiles for a region. Returns (success, total)."""
    region = REGIONS.get(region_name)
    if not region:
        logger.error(f"Unknown region: {region_name}")
        return 0, 0

    logger.info(f"\n{'='*60}")
    logger.info(f"Region: {region['description']}")
    logger.info(f"{'='*60}")

    success = 0
    total = len(region["tiles"])
    for lat, lon in region["tiles"]:
        if download_srtm_tile(lat, lon):
            success += 1

    return success, total


def download_full_quebec():
    """Download all SRTM tiles covering Quebec province."""
    logger.info("Downloading ALL Quebec SRTM tiles...")
    logger.info("Quebec bounds: lat 44-63, lon -80 to -57")

    success = 0
    total = 0
    for lat in range(44, 63):
        for lon in range(-80, -56):
            total += 1
            if download_srtm_tile(lat, lon):
                success += 1

    return success, total


def main():
    parser = argparse.ArgumentParser(description="Download terrain data for Quebec")
    parser.add_argument("--full", action="store_true", help="Download all Quebec tiles")
    parser.add_argument("--montreal", action="store_true", help="Montreal area only")
    parser.add_argument("--quebec-city", action="store_true", help="Quebec City area only")
    parser.add_argument("--region", type=str, help="Specific region name")
    parser.add_argument("--list-regions", action="store_true", help="List available regions")
    args = parser.parse_args()

    if args.list_regions:
        print("\nAvailable regions:")
        for name, info in REGIONS.items():
            print(f"  {name:20s} - {info['description']} ({len(info['tiles'])} tiles)")
        return

    print(f"""
========================================================
  RF Planner - Quebec Data Setup
  Downloading SRTM 30m elevation data
  Data directory: {str(DATA_DIR)}
========================================================
""")

    total_success = 0
    total_tiles = 0

    if args.full:
        s, t = download_full_quebec()
        total_success += s
        total_tiles += t
    elif args.montreal:
        s, t = download_region("montreal")
        total_success += s
        total_tiles += t
    elif args.quebec_city:
        s, t = download_region("quebec_city")
        total_success += s
        total_tiles += t
    elif args.region:
        s, t = download_region(args.region)
        total_success += s
        total_tiles += t
    else:
        # Default: download essential populated areas
        for region_name in ["montreal", "quebec_city", "trois_rivieres",
                           "sherbrooke", "gatineau", "saguenay"]:
            s, t = download_region(region_name)
            total_success += s
            total_tiles += t

    print(f"""
{'='*60}
Download complete: {total_success}/{total_tiles} tiles
Data directory: {SRTM_DIR}
{'='*60}

Next steps:
  1. Start the server:   docker-compose up
  2. Open browser:       http://localhost:3000
  3. Click on map to set transmitter position
  4. Configure parameters and click "Run"
""")


if __name__ == "__main__":
    main()
