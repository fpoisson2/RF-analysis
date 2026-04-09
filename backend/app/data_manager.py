"""
Data manager for downloading and managing terrain, building, and land cover data.
Focused on Quebec/Canada but supports global SRTM.

Data sources:
- Terrain: SRTM 1-arc-second (30m) from NASA / USGS
- Terrain (Canada): CDEM from Natural Resources Canada
- Buildings: Microsoft Building Footprints (free, global)
- Land cover: ESA WorldCover 10m (global)
- LiDAR: Données Québec (when available)
"""
import os
import io
import json
import struct
import zipfile
import logging
import hashlib
from pathlib import Path
from typing import Optional
from urllib.request import urlretrieve, urlopen, Request
from urllib.error import HTTPError

import numpy as np

logger = logging.getLogger(__name__)


class DataManager:
    """Manages terrain, building, and land cover data downloads and caching."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.srtm_dir = self.data_dir / "srtm"
        self.buildings_dir = self.data_dir / "buildings"
        self.landcover_dir = self.data_dir / "landcover"
        self.lidar_dir = self.data_dir / "lidar"
        self.cache_dir = self.data_dir / "cache"

        for d in [self.srtm_dir, self.buildings_dir, self.landcover_dir,
                  self.lidar_dir, self.cache_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ── SRTM Terrain Data ───────────────────────────────────────────────

    def get_srtm_tile_name(self, lat: float, lon: float) -> str:
        """Get SRTM HGT filename for a coordinate."""
        lat_prefix = "N" if lat >= 0 else "S"
        lon_prefix = "E" if lon >= 0 else "W"
        lat_int = int(abs(lat)) if lat >= 0 else int(abs(lat)) + (1 if lat != int(lat) else 0)
        lon_int = int(abs(lon)) if lon < 0 else int(abs(lon))
        if lat < 0 and lat != int(lat):
            lat_int = int(abs(lat)) + 1
        else:
            lat_int = int(abs(lat))
        if lon < 0 and lon != int(lon):
            lon_int = int(abs(lon)) + 1
        else:
            lon_int = int(abs(lon))
        return f"{lat_prefix}{lat_int:02d}{lon_prefix}{lon_int:03d}.hgt"

    def download_srtm_tile(self, lat: int, lon: int) -> Optional[Path]:
        """
        Download an SRTM tile for the given integer lat/lon.
        Tries multiple sources.
        Returns path to the .hgt file or None if not available.
        """
        tile_name = self._srtm_tile_name(lat, lon)
        hgt_path = self.srtm_dir / tile_name

        if hgt_path.exists():
            return hgt_path

        # Source 1: USGS SRTM via OpenTopography (no auth needed for 30m)
        sources = [
            f"https://elevation-tiles-prod.s3.amazonaws.com/skadi/{tile_name[:3]}/{tile_name}.gz",
        ]

        for url in sources:
            try:
                logger.info(f"Downloading SRTM tile {tile_name} from {url}...")
                req = Request(url, headers={"User-Agent": "RF-Planner/1.0"})
                response = urlopen(req, timeout=30)
                data = response.read()

                if url.endswith(".gz"):
                    import gzip
                    data = gzip.decompress(data)
                elif url.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        for name in zf.namelist():
                            if name.endswith(".hgt"):
                                data = zf.read(name)
                                break

                with open(hgt_path, "wb") as f:
                    f.write(data)
                logger.info(f"Downloaded {tile_name} ({len(data)} bytes)")
                return hgt_path
            except Exception as e:
                logger.warning(f"Failed to download from {url}: {e}")
                continue

        logger.warning(f"Could not download SRTM tile {tile_name}")
        return None

    def _srtm_tile_name(self, lat: int, lon: int) -> str:
        """Get SRTM tile filename from integer lat/lon."""
        lat_prefix = "N" if lat >= 0 else "S"
        lon_prefix = "E" if lon >= 0 else "W"
        return f"{lat_prefix}{abs(lat):02d}{lon_prefix}{abs(lon):03d}.hgt"

    def ensure_srtm_coverage(self, lat_min: float, lon_min: float,
                              lat_max: float, lon_max: float) -> list[Path]:
        """Download all SRTM tiles needed to cover a bounding box."""
        import math
        tiles = []
        for lat in range(math.floor(lat_min), math.ceil(lat_max)):
            for lon in range(math.floor(lon_min), math.ceil(lon_max)):
                path = self.download_srtm_tile(lat, lon)
                if path:
                    tiles.append(path)
        return tiles

    # ── Quebec / Canada specific ────────────────────────────────────────

    def download_quebec_coverage(self):
        """
        Download essential data for Quebec province.
        Quebec bounding box: lat 44.9-62.6, lon -80.0--56.9
        """
        logger.info("Downloading Quebec terrain data...")

        # Download SRTM tiles for populated areas of Quebec
        # Focus on St. Lawrence corridor (most populated)
        key_areas = [
            # Montreal area
            (45, -74), (45, -73), (45, -72),
            # Quebec City area
            (46, -72), (46, -71), (46, -70), (47, -71),
            # Trois-Rivières
            (46, -73),
            # Sherbrooke
            (45, -71), (45, -72),
            # Gatineau/Ottawa
            (45, -75), (45, -76),
            # Saguenay
            (48, -71), (48, -72),
            # Rimouski
            (48, -68), (48, -69),
        ]

        downloaded = []
        for lat, lon in key_areas:
            path = self.download_srtm_tile(lat, lon)
            if path:
                downloaded.append(str(path))

        return {
            "tiles_downloaded": len(downloaded),
            "paths": downloaded,
            "coverage": "Quebec St. Lawrence corridor",
        }

    # ── Microsoft Building Footprints ───────────────────────────────────

    def get_buildings_geojson(self, lat: float, lon: float, radius_km: float = 5) -> Optional[dict]:
        """
        Load building footprints for an area.
        Uses cached data if available, otherwise returns None.
        Buildings should be pre-downloaded for the region.
        """
        cache_key = f"buildings_{lat:.2f}_{lon:.2f}_{radius_km:.0f}"
        cache_path = self.cache_dir / f"{cache_key}.json"

        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)

        # Check if we have building data for this area
        # Microsoft Building Footprints are organized by region
        # For Quebec: download from https://github.com/microsoft/CanadianBuildingFootprints
        return None

    def download_canada_buildings(self, province: str = "Quebec") -> Optional[Path]:
        """
        Download Microsoft Building Footprints for a Canadian province.
        Source: https://github.com/microsoft/CanadianBuildingFootprints
        """
        url = f"https://usbuildingdata.blob.core.windows.net/canadian-buildings-v3/{province}.geojson.zip"
        output_path = self.buildings_dir / f"{province}.geojson"

        if output_path.exists():
            logger.info(f"Buildings data for {province} already exists")
            return output_path

        try:
            logger.info(f"Downloading building footprints for {province}...")
            req = Request(url, headers={"User-Agent": "RF-Planner/1.0"})
            response = urlopen(req, timeout=120)
            data = response.read()

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.endswith(".geojson"):
                        extracted = zf.read(name)
                        with open(output_path, "wb") as f:
                            f.write(extracted)
                        logger.info(f"Extracted {province} buildings ({len(extracted)} bytes)")
                        return output_path

            # If not zipped, write directly
            with open(output_path, "wb") as f:
                f.write(data)
            return output_path
        except Exception as e:
            logger.error(f"Failed to download buildings for {province}: {e}")
            return None

    # ── ESA WorldCover (Land Cover 10m) ─────────────────────────────────

    def get_landcover_class(self, code: int) -> dict:
        """Get land cover class info from ESA WorldCover code."""
        classes = {
            10: {"name": "Tree cover", "height": 12, "attenuation_db_m": 0.2, "color": "#006400"},
            20: {"name": "Shrubland", "height": 3, "attenuation_db_m": 0.1, "color": "#FFBB22"},
            30: {"name": "Grassland", "height": 0.5, "attenuation_db_m": 0.01, "color": "#FFFF4C"},
            40: {"name": "Cropland", "height": 1.5, "attenuation_db_m": 0.02, "color": "#F096FF"},
            50: {"name": "Built-up", "height": 8, "attenuation_db_m": 0.5, "color": "#FA0000"},
            60: {"name": "Bare/sparse", "height": 0, "attenuation_db_m": 0.0, "color": "#B4B4B4"},
            70: {"name": "Snow/ice", "height": 0, "attenuation_db_m": 0.0, "color": "#F0F0F0"},
            80: {"name": "Water", "height": 0, "attenuation_db_m": 0.0, "color": "#0064C8"},
            90: {"name": "Herbaceous wetland", "height": 1, "attenuation_db_m": 0.03, "color": "#0096A0"},
            95: {"name": "Mangroves", "height": 6, "attenuation_db_m": 0.15, "color": "#00CF75"},
            100: {"name": "Moss/lichen", "height": 0.1, "attenuation_db_m": 0.01, "color": "#FAE6A0"},
        }
        return classes.get(code, {"name": "Unknown", "height": 0, "attenuation_db_m": 0.0, "color": "#808080"})

    # ── Clutter Profile ─────────────────────────────────────────────────

    def get_clutter_profile(self, profile_name: str = "quebec_default") -> dict:
        """
        Get a clutter attenuation profile.
        Returns height (m) and attenuation (dB/m) for each land cover type.
        """
        profiles = {
            "quebec_default": {
                "name": "Quebec Default",
                "description": "Default clutter profile for Quebec province",
                "building_attenuation_db_m": 0.4,  # Brick/concrete mix
                "land_cover": {
                    10: {"height": 15, "attenuation_db_m": 0.25},  # Dense boreal forest
                    20: {"height": 3, "attenuation_db_m": 0.1},    # Shrubs
                    30: {"height": 0.5, "attenuation_db_m": 0.01}, # Grass
                    40: {"height": 1.5, "attenuation_db_m": 0.02}, # Crops
                    50: {"height": 10, "attenuation_db_m": 0.5},   # Urban
                    60: {"height": 0, "attenuation_db_m": 0.0},    # Bare
                    70: {"height": 0, "attenuation_db_m": 0.0},    # Snow
                    80: {"height": 0, "attenuation_db_m": 0.0},    # Water
                    90: {"height": 1, "attenuation_db_m": 0.03},   # Wetland
                },
            },
            "urban_dense": {
                "name": "Dense Urban",
                "description": "Dense urban environment (Montreal downtown)",
                "building_attenuation_db_m": 0.8,
                "land_cover": {
                    10: {"height": 8, "attenuation_db_m": 0.2},
                    20: {"height": 2, "attenuation_db_m": 0.05},
                    30: {"height": 0.3, "attenuation_db_m": 0.01},
                    40: {"height": 1, "attenuation_db_m": 0.02},
                    50: {"height": 20, "attenuation_db_m": 1.0},
                    60: {"height": 0, "attenuation_db_m": 0.0},
                    70: {"height": 0, "attenuation_db_m": 0.0},
                    80: {"height": 0, "attenuation_db_m": 0.0},
                    90: {"height": 0.5, "attenuation_db_m": 0.02},
                },
            },
            "rural_forest": {
                "name": "Rural Forest",
                "description": "Rural/forested area (Laurentides, Charlevoix)",
                "building_attenuation_db_m": 0.3,
                "land_cover": {
                    10: {"height": 18, "attenuation_db_m": 0.3},   # Tall boreal
                    20: {"height": 4, "attenuation_db_m": 0.15},
                    30: {"height": 0.5, "attenuation_db_m": 0.01},
                    40: {"height": 1.5, "attenuation_db_m": 0.02},
                    50: {"height": 6, "attenuation_db_m": 0.3},
                    60: {"height": 0, "attenuation_db_m": 0.0},
                    70: {"height": 0, "attenuation_db_m": 0.0},
                    80: {"height": 0, "attenuation_db_m": 0.0},
                    90: {"height": 1.5, "attenuation_db_m": 0.05},
                },
            },
        }
        return profiles.get(profile_name, profiles["quebec_default"])

    # ── Data Status ─────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get status of all data sources."""
        srtm_tiles = list(self.srtm_dir.glob("*.hgt"))
        buildings_files = list(self.buildings_dir.glob("*.geojson"))
        landcover_files = list(self.landcover_dir.glob("*"))

        return {
            "srtm": {
                "tiles": len(srtm_tiles),
                "files": [t.name for t in srtm_tiles[:20]],
                "dir": str(self.srtm_dir),
            },
            "buildings": {
                "files": len(buildings_files),
                "provinces": [f.stem for f in buildings_files],
                "dir": str(self.buildings_dir),
            },
            "landcover": {
                "files": len(landcover_files),
                "dir": str(self.landcover_dir),
            },
        }
