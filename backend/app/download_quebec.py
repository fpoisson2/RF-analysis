"""
Download Quebec City open data: buildings + LiDAR.

Sources:
- Bâtiments: Données Québec (Ville de Québec empreintes avec élévation)
- LiDAR: MERN via Données Québec (DTM/DSM GeoTIFF tiles)
"""
import os
import io
import csv
import json
import zipfile
import logging
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from typing import Optional

logger = logging.getLogger(__name__)

# ── URLs ──────────────────────────────────────────────────────────────

QUEBEC_CITY_BUILDINGS_GEOJSON = (
    "https://www.donneesquebec.ca/recherche/dataset/"
    "d2a34f6d-3750-44e9-9a6d-aa9494a34df7/resource/"
    "7fccf3b2-5694-4008-8edb-82d3feaa0b40/download/vdq-batiments.geojson"
)

LIDAR_TILE_INDEX_CSV = (
    "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/"
    "IMAGERIE/Produits_derives_LiDAR/Produit_derive_lidar/"
    "03-Telechargement/URL_Lidar.csv"
)

# Quebec City bounding box (approximate)
QUEBEC_CITY_BBOX = {
    "lat_min": 46.72,
    "lat_max": 46.95,
    "lon_min": -71.40,
    "lon_max": -71.10,
}

HEADERS = {"User-Agent": "RF-Planner/1.0"}


def download_file(url: str, output_path: Path, description: str = "") -> bool:
    """Download a file with progress logging."""
    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info(f"Already downloaded: {output_path.name}")
        return True
    try:
        logger.info(f"Downloading {description or url}...")
        req = Request(url, headers=HEADERS)
        response = urlopen(req, timeout=120)
        data = response.read()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(data)
        logger.info(f"  OK: {output_path.name} ({len(data):,} bytes)")
        return True
    except Exception as e:
        logger.error(f"  FAILED: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════
# Buildings - Ville de Québec
# ══════════════════════════════════════════════════════════════════════

def download_quebec_city_buildings(data_dir: str) -> dict:
    """
    Download building footprints for Quebec City from Données Québec.
    Includes elevation data (ELEVATION field).
    """
    buildings_dir = Path(data_dir) / "buildings"
    buildings_dir.mkdir(parents=True, exist_ok=True)
    output_path = buildings_dir / "quebec_city_batiments.geojson"

    if output_path.exists():
        size_mb = output_path.stat().st_size / 1e6
        logger.info(f"Buildings already downloaded: {output_path} ({size_mb:.1f} MB)")
        # Count features
        try:
            with open(output_path) as f:
                data = json.load(f)
            n_features = len(data.get("features", []))
        except Exception:
            n_features = -1
        return {
            "status": "already_downloaded",
            "path": str(output_path),
            "size_mb": round(size_mb, 1),
            "features": n_features,
        }

    success = download_file(
        QUEBEC_CITY_BUILDINGS_GEOJSON,
        output_path,
        "Ville de Québec - Empreintes des bâtiments"
    )

    if success:
        size_mb = output_path.stat().st_size / 1e6
        try:
            with open(output_path) as f:
                data = json.load(f)
            n_features = len(data.get("features", []))
        except Exception:
            n_features = -1
        return {
            "status": "downloaded",
            "path": str(output_path),
            "size_mb": round(size_mb, 1),
            "features": n_features,
        }
    return {"status": "failed"}


# ══════════════════════════════════════════════════════════════════════
# LiDAR - MERN / Données Québec
# ══════════════════════════════════════════════════════════════════════

def get_lidar_tile_index(data_dir: str) -> list[dict]:
    """
    Download and parse the LiDAR tile index CSV.
    Returns list of tiles with URLs and bounding boxes.
    """
    cache_path = Path(data_dir) / "lidar" / "tile_index.csv"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if not cache_path.exists():
        download_file(LIDAR_TILE_INDEX_CSV, cache_path, "LiDAR tile index")

    if not cache_path.exists():
        logger.error("Could not download LiDAR tile index")
        return []

    tiles = []
    try:
        with open(cache_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                tiles.append(row)
    except Exception as e:
        # Try comma delimiter
        try:
            with open(cache_path, newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f, delimiter=',')
                for row in reader:
                    tiles.append(row)
        except Exception as e2:
            logger.error(f"Could not parse tile index: {e2}")
            # Log first few lines for debugging
            with open(cache_path, encoding='utf-8-sig') as f:
                for i, line in enumerate(f):
                    if i < 5:
                        logger.info(f"  Line {i}: {line.strip()}")

    logger.info(f"LiDAR tile index: {len(tiles)} tiles total")
    return tiles


def find_tiles_for_bbox(tiles: list[dict], bbox: dict) -> list[dict]:
    """Find LiDAR tiles that intersect a bounding box."""
    matching = []
    for tile in tiles:
        # Try various column name patterns for coordinates
        try:
            # Common column names in Quebec LiDAR index
            lat = lon = None
            for lat_key in ['LAT', 'Latitude', 'latitude', 'Y', 'y', 'CENT_LAT']:
                if lat_key in tile:
                    lat = float(tile[lat_key].replace(',', '.'))
                    break
            for lon_key in ['LON', 'LONG', 'Longitude', 'longitude', 'X', 'x', 'CENT_LONG']:
                if lon_key in tile:
                    lon = float(tile[lon_key].replace(',', '.'))
                    break

            if lat is None or lon is None:
                continue

            if (bbox["lat_min"] <= lat <= bbox["lat_max"] and
                bbox["lon_min"] <= lon <= bbox["lon_max"]):
                matching.append(tile)
        except (ValueError, KeyError):
            continue

    logger.info(f"Found {len(matching)} LiDAR tiles in bbox")
    return matching


def download_lidar_tiles_quebec_city(data_dir: str, max_tiles: int = 20) -> dict:
    """
    Download LiDAR-derived DTM/DSM tiles for Quebec City area.
    """
    lidar_dir = Path(data_dir) / "lidar" / "quebec_city"
    lidar_dir.mkdir(parents=True, exist_ok=True)

    # Get tile index
    tiles = get_lidar_tile_index(data_dir)
    if not tiles:
        # If CSV parsing failed, try direct known tile URLs
        return _download_known_quebec_city_tiles(lidar_dir)

    # Find tiles covering Quebec City
    matching = find_tiles_for_bbox(tiles, QUEBEC_CITY_BBOX)

    if not matching:
        logger.warning("No matching tiles found in index, trying known URLs")
        return _download_known_quebec_city_tiles(lidar_dir)

    downloaded = []
    for tile in matching[:max_tiles]:
        # Find URL column
        url = None
        for url_key in ['URL', 'url', 'URL_MNT', 'URL_DTM', 'lien_mnt',
                        'LIEN_MNT', 'download', 'DOWNLOAD']:
            if url_key in tile and tile[url_key].startswith('http'):
                url = tile[url_key]
                break

        if not url:
            # Try to find any URL-like value
            for v in tile.values():
                if isinstance(v, str) and v.startswith('http') and ('.tif' in v.lower() or '.zip' in v.lower()):
                    url = v
                    break

        if url:
            filename = url.split('/')[-1]
            output_path = lidar_dir / filename
            if download_file(url, output_path, f"LiDAR tile {filename}"):
                downloaded.append(str(output_path))

    return {
        "status": "downloaded",
        "tiles_found": len(matching),
        "tiles_downloaded": len(downloaded),
        "paths": downloaded,
        "directory": str(lidar_dir),
    }


def _download_known_quebec_city_tiles(lidar_dir: Path) -> dict:
    """
    Fallback: try known LiDAR tile URLs for Quebec City region.
    Quebec City is in SNRC sheet 21L (1:250k) and feuillets 21L/06, 21L/07, 21L/11, 21L/14.
    """
    # Known base URL pattern for MERN LiDAR products
    base_urls = [
        "https://diffusion.mern.gouv.qc.ca/diffusion/RGQ/Lidar/21L/Modele_numerique_terrain/",
        "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/IMAGERIE/Produits_derives_LiDAR/",
    ]

    # Known sheet numbers covering Quebec City
    sheets = ["21L06", "21L07", "21L11", "21L14"]

    downloaded = []
    for sheet in sheets:
        for base in base_urls:
            # Try common filename patterns
            patterns = [
                f"{base}{sheet}_mnt.tif",
                f"{base}{sheet}_MNT.tif",
                f"{base}{sheet}/{sheet}_mnt_1m.tif",
                f"{base}{sheet}/{sheet}_MNT_1m.tif",
            ]
            for url in patterns:
                output_path = lidar_dir / f"{sheet}_mnt.tif"
                if output_path.exists():
                    downloaded.append(str(output_path))
                    break
                if download_file(url, output_path, f"LiDAR DTM {sheet}"):
                    downloaded.append(str(output_path))
                    break
                else:
                    # Clean up empty/failed file
                    if output_path.exists() and output_path.stat().st_size == 0:
                        output_path.unlink()

    return {
        "status": "attempted",
        "tiles_downloaded": len(downloaded),
        "paths": downloaded,
        "directory": str(lidar_dir),
        "note": "Some tiles may not be available via direct download. Visit https://www.donneesquebec.ca/recherche/dataset/produits-derives-de-base-du-lidar",
    }


# ══════════════════════════════════════════════════════════════════════
# Combined download
# ══════════════════════════════════════════════════════════════════════

def download_all_quebec_city(data_dir: str) -> dict:
    """Download all available data for Quebec City."""
    results = {}

    logger.info("=" * 60)
    logger.info("Downloading Quebec City data...")
    logger.info("=" * 60)

    # Buildings
    logger.info("\n--- Buildings ---")
    results["buildings"] = download_quebec_city_buildings(data_dir)

    # LiDAR
    logger.info("\n--- LiDAR ---")
    results["lidar"] = download_lidar_tiles_quebec_city(data_dir)

    return results
