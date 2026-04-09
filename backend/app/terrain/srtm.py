"""
SRTM terrain data manager.

Loads SRTM HGT files (1-arc-second = 30m or 3-arc-second = 90m).
Provides elevation queries and terrain profile extraction.
Auto-downloads tiles from AWS when needed.
"""
import os
import gzip
import math
import struct
import logging
from pathlib import Path
from typing import Optional, Tuple
from functools import lru_cache
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import numpy as np

logger = logging.getLogger(__name__)

# Earth radius in meters
EARTH_RADIUS = 6371000.0


class SRTMManager:
    """Manages SRTM elevation data with automatic download and caching."""

    def __init__(self, data_dir: str, auto_download: bool = True):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.auto_download = auto_download
        self._tile_cache = {}
        self._max_cache_tiles = 20

    def get_elevation(self, lat: float, lon: float) -> float:
        """
        Get elevation at a point with bilinear interpolation.
        Returns elevation in meters (0 if no data).
        """
        tile = self._get_tile(lat, lon)
        if tile is None:
            return 0.0

        data, size = tile
        # Position within tile
        lat_frac = lat - math.floor(lat)
        lon_frac = lon - math.floor(lon)

        # Pixel coordinates (SRTM tiles start from bottom-left)
        row = (1.0 - lat_frac) * (size - 1)
        col = lon_frac * (size - 1)

        r0 = int(row)
        c0 = int(col)
        r1 = min(r0 + 1, size - 1)
        c1 = min(c0 + 1, size - 1)

        # Bilinear interpolation weights
        dr = row - r0
        dc = col - c0

        # Four corner values
        z00 = float(data[r0, c0])
        z01 = float(data[r0, c1])
        z10 = float(data[r1, c0])
        z11 = float(data[r1, c1])

        # Handle void values (-32768)
        for z in [z00, z01, z10, z11]:
            if z <= -32768:
                return 0.0

        # Bilinear interpolation
        z = (z00 * (1 - dr) * (1 - dc) +
             z01 * (1 - dr) * dc +
             z10 * dr * (1 - dc) +
             z11 * dr * dc)

        return max(0.0, z)

    def get_profile(self, lat1: float, lon1: float,
                     lat2: float, lon2: float,
                     num_points: int = 100) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract elevation profile along a great circle path.

        Args:
            lat1, lon1: Start point
            lat2, lon2: End point
            num_points: Number of sample points

        Returns:
            (distances_m, elevations_m) - Arrays of distances and elevations
        """
        lats = np.linspace(lat1, lat2, num_points)
        lons = np.linspace(lon1, lon2, num_points)

        elevations = np.zeros(num_points)
        for i in range(num_points):
            elevations[i] = self.get_elevation(lats[i], lons[i])

        # Calculate cumulative distances
        distances = np.zeros(num_points)
        for i in range(1, num_points):
            distances[i] = distances[i-1] + haversine_distance(
                lats[i-1], lons[i-1], lats[i], lons[i]
            )

        return distances, elevations

    def get_elevation_grid(self, lat_center: float, lon_center: float,
                            radius_km: float, resolution_m: float
                            ) -> Tuple[np.ndarray, dict]:
        """
        Get an elevation grid centered on a point.

        Returns:
            (grid, metadata) where grid is 2D array of elevations
        """
        # Grid dimensions
        n_cells = int(2 * radius_km * 1000 / resolution_m)
        n_cells = max(10, min(n_cells, 4000))  # Limit grid size

        cos_lat = math.cos(math.radians(lat_center))
        lat_per_m = 1.0 / 111320.0
        lon_per_m = 1.0 / (111320.0 * cos_lat)

        half_extent_lat = radius_km * 1000 * lat_per_m
        half_extent_lon = radius_km * 1000 * lon_per_m

        lat_min = lat_center - half_extent_lat
        lat_max = lat_center + half_extent_lat
        lon_min = lon_center - half_extent_lon
        lon_max = lon_center + half_extent_lon

        lats = np.linspace(lat_max, lat_min, n_cells)  # Top to bottom
        lons = np.linspace(lon_min, lon_max, n_cells)

        grid = np.zeros((n_cells, n_cells), dtype=np.float32)
        for r in range(n_cells):
            for c in range(n_cells):
                grid[r, c] = self.get_elevation(lats[r], lons[c])

        metadata = {
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
            "n_cells": n_cells,
            "resolution_m": resolution_m,
        }

        return grid, metadata

    def _get_tile(self, lat: float, lon: float) -> Optional[Tuple[np.ndarray, int]]:
        """Load and cache an SRTM tile."""
        tile_lat = math.floor(lat)
        tile_lon = math.floor(lon)
        key = (tile_lat, tile_lon)

        if key in self._tile_cache:
            return self._tile_cache[key]

        tile_name = self._tile_filename(tile_lat, tile_lon)
        tile_path = self.data_dir / tile_name

        if not tile_path.exists() and self.auto_download:
            self._download_tile(tile_lat, tile_lon)

        if not tile_path.exists():
            logger.debug(f"No SRTM data for {tile_name}")
            return None

        data, size = self._load_hgt(tile_path)

        # Cache management
        if len(self._tile_cache) >= self._max_cache_tiles:
            oldest = next(iter(self._tile_cache))
            del self._tile_cache[oldest]

        self._tile_cache[key] = (data, size)
        return (data, size)

    def _load_hgt(self, path: Path) -> Tuple[np.ndarray, int]:
        """Load an HGT file into a numpy array."""
        file_size = path.stat().st_size
        # Determine resolution from file size
        if file_size == 3601 * 3601 * 2:
            size = 3601  # 1-arc-second (~30m)
        elif file_size == 1201 * 1201 * 2:
            size = 1201  # 3-arc-second (~90m)
        else:
            # Try to guess
            n = int(math.sqrt(file_size / 2))
            if n * n * 2 == file_size:
                size = n
            else:
                logger.warning(f"Unknown HGT file size: {file_size} bytes for {path.name}")
                size = 1201

        with open(path, "rb") as f:
            raw = f.read()

        data = np.frombuffer(raw, dtype=np.dtype(">i2")).reshape((size, size))
        # Replace void values
        data = data.astype(np.float32)
        data[data <= -32768] = 0.0

        return data, size

    def _tile_filename(self, lat: int, lon: int) -> str:
        """Generate SRTM tile filename."""
        lat_prefix = "N" if lat >= 0 else "S"
        lon_prefix = "E" if lon >= 0 else "W"
        return f"{lat_prefix}{abs(lat):02d}{lon_prefix}{abs(lon):03d}.hgt"

    def _download_tile(self, lat: int, lon: int):
        """Download an SRTM tile from AWS."""
        name = self._tile_filename(lat, lon)
        path = self.data_dir / name

        if path.exists():
            return

        tile_prefix = name[:3]  # e.g., "N46"
        url = f"https://elevation-tiles-prod.s3.amazonaws.com/skadi/{tile_prefix}/{name}.gz"

        try:
            logger.info(f"Downloading SRTM tile {name} from AWS...")
            req = Request(url, headers={"User-Agent": "RF-Planner/1.0"})
            response = urlopen(req, timeout=60)
            compressed = response.read()
            data = gzip.decompress(compressed)

            with open(path, "wb") as f:
                f.write(data)
            logger.info(f"Downloaded {name} ({len(data):,} bytes)")
        except HTTPError as e:
            if e.code == 404:
                logger.debug(f"SRTM tile {name} not available (ocean)")
            else:
                logger.warning(f"Failed to download {name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to download {name}: {e}")

    def get_loaded_tiles(self) -> list[str]:
        """List loaded tiles in cache."""
        return [self._tile_filename(k[0], k[1]) for k in self._tile_cache]

    def get_available_tiles(self) -> list[str]:
        """List available .hgt files on disk."""
        return [f.name for f in self.data_dir.glob("*.hgt")]


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in meters."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    return EARTH_RADIUS * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate initial bearing from point 1 to point 2 in degrees."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def destination_point(lat: float, lon: float, bearing_deg: float, distance_m: float) -> Tuple[float, float]:
    """Calculate destination point given start, bearing, and distance."""
    lat = math.radians(lat)
    lon = math.radians(lon)
    bearing_rad = math.radians(bearing_deg)
    d = distance_m / EARTH_RADIUS

    lat2 = math.asin(math.sin(lat) * math.cos(d) + math.cos(lat) * math.sin(d) * math.cos(bearing_rad))
    lon2 = lon + math.atan2(
        math.sin(bearing_rad) * math.sin(d) * math.cos(lat),
        math.cos(d) - math.sin(lat) * math.sin(lat2)
    )
    return math.degrees(lat2), math.degrees(lon2)
