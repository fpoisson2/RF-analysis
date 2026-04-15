"""
LiDAR terrain manager for MERN Quebec GeoTIFF tiles.

Provides the same interface as SRTMManager but uses 1m LiDAR data
when available, falling back to SRTM for areas without LiDAR coverage.

Supports both MNT (terrain nu) and MHC (hauteur canopée = bâtiments + arbres).
CRS: EPSG:2949 (NAD83 MTM zone 7) → converted from/to EPSG:4326 (lat/lon).
"""
import os
import math
import logging
from pathlib import Path
from typing import Optional, Tuple
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

try:
    import rasterio
    from rasterio.windows import from_bounds
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    from pyproj import Transformer
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False


class LiDARTerrainManager:
    """
    High-resolution terrain using MERN LiDAR GeoTIFFs.
    Falls back to a base terrain manager (SRTM) when LiDAR is not available.
    """

    def __init__(self, lidar_dir: str, fallback_manager=None):
        self.lidar_dir = Path(lidar_dir)
        self.fallback = fallback_manager
        self._tiles_mnt = {}  # {path: rasterio dataset} for DTM
        self._tiles_mhc = {}  # {path: rasterio dataset} for canopy height
        self._tile_index = []  # [(bounds_4326, path_mnt, path_mhc)]
        self._transformer_to_local = None
        self._transformer_to_wgs84 = None

        if not HAS_RASTERIO:
            logger.warning("rasterio not installed - LiDAR disabled")
            return
        if not HAS_PYPROJ:
            logger.warning("pyproj not installed - LiDAR disabled")
            return

        self._scan_tiles()

    def _scan_tiles(self):
        """Scan the LiDAR directory and build a tile index."""
        if not self.lidar_dir.exists():
            return

        mnt_files = sorted(self.lidar_dir.glob("MNT_*.tif"))
        if not mnt_files:
            # Check subdirectories
            mnt_files = sorted(self.lidar_dir.rglob("MNT_*.tif"))

        if not mnt_files:
            logger.info("No LiDAR MNT tiles found")
            return

        for mnt_path in mnt_files:
            try:
                with rasterio.open(mnt_path) as ds:
                    crs = ds.crs
                    bounds = ds.bounds

                # Create transformer for this CRS
                if self._transformer_to_wgs84 is None:
                    self._transformer_to_wgs84 = Transformer.from_crs(
                        crs, "EPSG:4326", always_xy=True
                    )
                    self._transformer_to_local = Transformer.from_crs(
                        "EPSG:4326", crs, always_xy=True
                    )

                # Convert bounds to WGS84
                lon_min, lat_min = self._transformer_to_wgs84.transform(bounds.left, bounds.bottom)
                lon_max, lat_max = self._transformer_to_wgs84.transform(bounds.right, bounds.top)

                # Find matching MHC file
                tile_id = mnt_path.stem.replace("MNT_", "")
                mhc_path = mnt_path.parent / f"MHC_{tile_id}.tif"

                self._tile_index.append({
                    "mnt_path": str(mnt_path),
                    "mhc_path": str(mhc_path) if mhc_path.exists() else None,
                    "bounds_local": (bounds.left, bounds.bottom, bounds.right, bounds.top),
                    "bounds_wgs84": (lon_min, lat_min, lon_max, lat_max),
                    "crs": str(crs),
                    "tile_id": tile_id,
                })
            except Exception as e:
                logger.warning(f"Could not read {mnt_path}: {e}")

        logger.info(f"LiDAR: {len(self._tile_index)} MNT tiles indexed, "
                    f"{sum(1 for t in self._tile_index if t['mhc_path'])} with MHC")

    def _find_tile(self, lat: float, lon: float) -> Optional[dict]:
        """Find the LiDAR tile covering a lat/lon point."""
        for tile in self._tile_index:
            b = tile["bounds_wgs84"]
            if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]:
                return tile
        return None

    def _get_dataset(self, path: str, cache: dict) -> Optional[any]:
        """Get or open a rasterio dataset with caching."""
        if path in cache:
            return cache[path]
        if not os.path.exists(path):
            return None
        try:
            ds = rasterio.open(path)
            cache[path] = ds
            return ds
        except Exception as e:
            logger.warning(f"Could not open {path}: {e}")
            return None

    def get_elevation(self, lat: float, lon: float, use_canopy: bool = False) -> float:
        """
        Get elevation at a point.
        Uses LiDAR MNT (terrain) or MHC (canopy) when available,
        falls back to SRTM.

        Args:
            lat, lon: WGS84 coordinates
            use_canopy: If True, adds canopy/building height (MHC) to terrain
        """
        if not HAS_RASTERIO or not self._tile_index:
            return self.fallback.get_elevation(lat, lon) if self.fallback else 0.0

        tile = self._find_tile(lat, lon)
        if tile is None:
            return self.fallback.get_elevation(lat, lon) if self.fallback else 0.0

        # Convert to local CRS
        x, y = self._transformer_to_local.transform(lon, lat)

        # Read MNT (terrain)
        mnt_ds = self._get_dataset(tile["mnt_path"], self._tiles_mnt)
        if mnt_ds is None:
            return self.fallback.get_elevation(lat, lon) if self.fallback else 0.0

        try:
            row, col = mnt_ds.index(x, y)
            if 0 <= row < mnt_ds.height and 0 <= col < mnt_ds.width:
                elev = float(mnt_ds.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                if elev < -1000 or np.isnan(elev):
                    elev = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
            else:
                elev = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
        except Exception:
            elev = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0

        # Add canopy height if requested
        if use_canopy and tile["mhc_path"]:
            mhc_ds = self._get_dataset(tile["mhc_path"], self._tiles_mhc)
            if mhc_ds:
                try:
                    row, col = mhc_ds.index(x, y)
                    if 0 <= row < mhc_ds.height and 0 <= col < mhc_ds.width:
                        canopy = float(mhc_ds.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                        if not np.isnan(canopy) and canopy > 0:
                            elev += canopy
                except Exception:
                    pass

        return elev

    def get_profile(self, lat1: float, lon1: float,
                     lat2: float, lon2: float,
                     num_points: int = 200,
                     use_canopy: bool = False) -> Tuple[np.ndarray, np.ndarray]:
        """Extract elevation profile, using LiDAR when available."""
        lats = np.linspace(lat1, lat2, num_points)
        lons = np.linspace(lon1, lon2, num_points)

        elevations = np.zeros(num_points, dtype=np.float32)
        for i in range(num_points):
            elevations[i] = self.get_elevation(lats[i], lons[i], use_canopy=use_canopy)

        # Cumulative distances
        distances = np.zeros(num_points, dtype=np.float32)
        for i in range(1, num_points):
            dlat = (lats[i] - lats[i-1]) * 111320
            dlon = (lons[i] - lons[i-1]) * 111320 * math.cos(math.radians(lats[i]))
            distances[i] = distances[i-1] + math.sqrt(dlat**2 + dlon**2)

        return distances, elevations

    def _sample_surface(self, lat: float, lon: float) -> tuple[float, float]:
        """Sample (ground, canopy_height) at a single (lat, lon). Returns
        (NaN, 0) if outside LiDAR coverage."""
        tile = self._find_tile(lat, lon)
        if tile is None:
            g = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
            return g, 0.0
        x, y = self._transformer_to_local.transform(lon, lat)
        g = 0.0
        c = 0.0
        mnt_ds = self._get_dataset(tile["mnt_path"], self._tiles_mnt)
        if mnt_ds is not None:
            try:
                row, col = mnt_ds.index(x, y)
                if 0 <= row < mnt_ds.height and 0 <= col < mnt_ds.width:
                    g = float(mnt_ds.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                    if g < -1000 or np.isnan(g):
                        g = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
            except Exception:
                g = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
        if tile["mhc_path"]:
            mhc_ds = self._get_dataset(tile["mhc_path"], self._tiles_mhc)
            if mhc_ds is not None:
                try:
                    row, col = mhc_ds.index(x, y)
                    if 0 <= row < mhc_ds.height and 0 <= col < mhc_ds.width:
                        v = float(mhc_ds.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                        if not np.isnan(v) and v > 0:
                            c = v
                except Exception:
                    pass
        return g, c

    def get_swath_max_surface(self, lats: np.ndarray, lons: np.ndarray,
                               widths_m: np.ndarray, num_offsets: int = 5) -> np.ndarray:
        """For each sample point, return the MAX surface elevation (ground+canopy)
        within a ±widths_m/2 band perpendicular to the path direction.
        Used for obstruction detection against the Fresnel zone width.
        """
        n = len(lats)
        out = np.zeros(n, dtype=np.float32)
        if n < 2 or not HAS_RASTERIO or not self._tile_index:
            # fall back to centerline
            for i in range(n):
                g, c = self._sample_surface(float(lats[i]), float(lons[i]))
                out[i] = g + c
            return out

        # Path bearing at each sample (using neighbors). In local tangent plane,
        # perpendicular is rotated 90° from (dlon, dlat).
        for i in range(n):
            # centerline
            g, c = self._sample_surface(float(lats[i]), float(lons[i]))
            best = g + c

            # finite-difference direction
            i0 = max(0, i - 1)
            i1 = min(n - 1, i + 1)
            dlat = float(lats[i1] - lats[i0])
            dlon = float(lons[i1] - lons[i0])
            seg_m = math.hypot(dlat * 111320,
                               dlon * 111320 * math.cos(math.radians(float(lats[i]))))
            if seg_m <= 0:
                out[i] = best
                continue
            # perpendicular unit vector (rotate +90° in lat/lon space, scaled for longitude)
            cos_lat = math.cos(math.radians(float(lats[i])))
            # normalize direction to meters, then perpendicular
            dir_e = (dlon * cos_lat * 111320) / seg_m
            dir_n = (dlat * 111320) / seg_m
            perp_e = -dir_n
            perp_n = dir_e
            half = float(widths_m[i]) * 0.5
            if half <= 0.5:
                out[i] = best
                continue
            for k in range(1, num_offsets + 1):
                off = half * (k / num_offsets)
                for sign in (-1.0, 1.0):
                    d_e = perp_e * off * sign
                    d_n = perp_n * off * sign
                    dlat_m = d_n / 111320.0
                    dlon_m = d_e / (111320.0 * cos_lat)
                    g2, c2 = self._sample_surface(float(lats[i]) + dlat_m,
                                                    float(lons[i]) + dlon_m)
                    v = g2 + c2
                    if v > best:
                        best = v
            out[i] = best
        return out

    def get_profile_detailed(self, lat1: float, lon1: float,
                              lat2: float, lon2: float,
                              num_points: int = 200) -> dict:
        """
        Extract a profile with separated ground (MNT) and surface (MNT+MHC)
        elevations. The canopy_height array is the MHC value at each sample —
        positive means there's an obstacle (tree or building) above ground.

        Returns a dict with numpy arrays: distances, lats, lons, ground, surface,
        canopy_height. Falls back to get_profile() + zero canopy when LiDAR isn't
        available.
        """
        lats = np.linspace(lat1, lat2, num_points)
        lons = np.linspace(lon1, lon2, num_points)

        ground = np.zeros(num_points, dtype=np.float32)
        canopy = np.zeros(num_points, dtype=np.float32)

        if not HAS_RASTERIO or not self._tile_index:
            for i in range(num_points):
                ground[i] = self.fallback.get_elevation(lats[i], lons[i]) if self.fallback else 0.0
        else:
            for i in range(num_points):
                lat, lon = float(lats[i]), float(lons[i])
                tile = self._find_tile(lat, lon)
                if tile is None:
                    ground[i] = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
                    continue

                x, y = self._transformer_to_local.transform(lon, lat)

                mnt_ds = self._get_dataset(tile["mnt_path"], self._tiles_mnt)
                if mnt_ds is not None:
                    try:
                        row, col = mnt_ds.index(x, y)
                        if 0 <= row < mnt_ds.height and 0 <= col < mnt_ds.width:
                            g = float(mnt_ds.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                            if g < -1000 or np.isnan(g):
                                g = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0
                            ground[i] = g
                    except Exception:
                        ground[i] = self.fallback.get_elevation(lat, lon) if self.fallback else 0.0

                if tile["mhc_path"]:
                    mhc_ds = self._get_dataset(tile["mhc_path"], self._tiles_mhc)
                    if mhc_ds is not None:
                        try:
                            row, col = mhc_ds.index(x, y)
                            if 0 <= row < mhc_ds.height and 0 <= col < mhc_ds.width:
                                c = float(mhc_ds.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                                if not np.isnan(c) and c > 0:
                                    canopy[i] = c
                        except Exception:
                            pass

        surface = ground + canopy

        distances = np.zeros(num_points, dtype=np.float32)
        for i in range(1, num_points):
            dlat = (lats[i] - lats[i-1]) * 111320
            dlon = (lons[i] - lons[i-1]) * 111320 * math.cos(math.radians(lats[i]))
            distances[i] = distances[i-1] + math.sqrt(dlat**2 + dlon**2)

        return {
            "distances": distances,
            "lats": lats.astype(np.float32),
            "lons": lons.astype(np.float32),
            "ground": ground,
            "surface": surface,
            "canopy_height": canopy,
        }

    def get_elevation_grid(self, lat_center: float, lon_center: float,
                            radius_km: float, resolution_m: float,
                            use_canopy: bool = False) -> Tuple[np.ndarray, dict]:
        """Get elevation grid, using LiDAR when available."""
        n_cells = int(2 * radius_km * 1000 / resolution_m)
        n_cells = max(10, min(n_cells, 4000))

        cos_lat = math.cos(math.radians(lat_center))
        lat_per_m = 1.0 / 111320.0
        lon_per_m = 1.0 / (111320.0 * cos_lat)
        half_lat = radius_km * 1000 * lat_per_m
        half_lon = radius_km * 1000 * lon_per_m

        lats = np.linspace(lat_center + half_lat, lat_center - half_lat, n_cells)
        lons = np.linspace(lon_center - half_lon, lon_center + half_lon, n_cells)

        grid = np.zeros((n_cells, n_cells), dtype=np.float32)
        for r in range(n_cells):
            for c in range(n_cells):
                grid[r, c] = self.get_elevation(lats[r], lons[c], use_canopy=use_canopy)

        metadata = {
            "lat_min": lat_center - half_lat,
            "lat_max": lat_center + half_lat,
            "lon_min": lon_center - half_lon,
            "lon_max": lon_center + half_lon,
            "n_cells": n_cells,
            "resolution_m": resolution_m,
        }
        return grid, metadata

    def read_block(self, lat_min: float, lon_min: float,
                    lat_max: float, lon_max: float,
                    dataset_type: str = "mnt",
                    max_pixels: int = 2000) -> Optional[Tuple[np.ndarray, dict]]:
        """
        Read a rectangular block from LiDAR GeoTIFFs, mosaicking multiple tiles.
        Output is in WGS84 grid (lat/lon aligned) to avoid projection offset.

        Args:
            lat_min, lon_min, lat_max, lon_max: WGS84 bounding box
            dataset_type: "mnt" (DTM) or "mhc" (canopy height)
            max_pixels: Max dimension to cap output size

        Returns:
            (data_array, metadata) or None if no coverage
        """
        if not HAS_RASTERIO or not self._tile_index or not self._transformer_to_local:
            return None

        from rasterio.enums import Resampling

        # Output grid in WGS84 coordinates
        # Compute output dimensions based on ~native resolution
        extent_m_x = (lon_max - lon_min) * 111320 * math.cos(math.radians((lat_min + lat_max) / 2))
        extent_m_y = (lat_max - lat_min) * 111320
        native_res = 1.0  # LiDAR is 1m

        out_w = min(max_pixels, int(extent_m_x / native_res))
        out_h = min(max_pixels, int(extent_m_y / native_res))
        out_w = max(10, out_w)
        out_h = max(10, out_h)

        actual_res = extent_m_x / out_w

        # Create output grid (WGS84 aligned)
        output = np.full((out_h, out_w), np.nan, dtype=np.float32)

        # For each pixel in output, compute its local CRS coordinate and sample
        # We do this in bulk per tile for efficiency
        lats = np.linspace(lat_max, lat_min, out_h)  # top to bottom
        lons = np.linspace(lon_min, lon_max, out_w)
        lon_grid, lat_grid = np.meshgrid(lons, lats)

        # Transform entire grid to local CRS
        x_grid, y_grid = self._transformer_to_local.transform(
            lon_grid.ravel(), lat_grid.ravel()
        )
        x_grid = np.array(x_grid).reshape(out_h, out_w)
        y_grid = np.array(y_grid).reshape(out_h, out_w)

        # Find all tiles that overlap
        x_min_all, y_min_all = x_grid.min(), y_grid.min()
        x_max_all, y_max_all = x_grid.max(), y_grid.max()

        path_key = "mnt_path" if dataset_type == "mnt" else "mhc_path"
        cache = self._tiles_mnt if dataset_type == "mnt" else self._tiles_mhc
        tiles_used = []

        for tile in self._tile_index:
            tb = tile["bounds_local"]
            # Check overlap
            if tb[0] > x_max_all or tb[2] < x_min_all or tb[1] > y_max_all or tb[3] < y_min_all:
                continue

            fpath = tile.get(path_key)
            if not fpath or not os.path.exists(fpath):
                continue

            ds = self._get_dataset(fpath, cache)
            if ds is None:
                continue

            try:
                # Use actual dataset bounds (from rasterio) with a small buffer
                # to avoid gaps between adjacent tiles
                buf = 50  # 50m buffer to cover gaps
                db = ds.bounds
                mask = ((x_grid >= db.left - buf) & (x_grid <= db.right + buf) &
                        (y_grid >= db.bottom - buf) & (y_grid <= db.top + buf))

                if not np.any(mask):
                    continue

                # Get pixel coordinates in the GeoTIFF for masked pixels
                xs = x_grid[mask]
                ys = y_grid[mask]

                # Convert to pixel coords using the dataset's transform
                inv_transform = ~ds.transform
                cols, rows = inv_transform * (xs, ys)
                cols = np.clip(cols.astype(int), 0, ds.width - 1)
                rows = np.clip(rows.astype(int), 0, ds.height - 1)

                # Read the required window (bounding box of needed pixels)
                r_min, r_max = int(rows.min()), int(rows.max()) + 1
                c_min, c_max = int(cols.min()), int(cols.max()) + 1
                r_min = max(0, r_min)
                c_min = max(0, c_min)
                r_max = min(ds.height, r_max)
                c_max = min(ds.width, c_max)

                window = rasterio.windows.Window(c_min, r_min, c_max - c_min, r_max - r_min)

                # Downsample if window is very large
                win_w = c_max - c_min
                win_h = r_max - r_min
                read_w = min(win_w, max_pixels)
                read_h = min(win_h, max_pixels)

                tile_data = ds.read(1, window=window,
                                     out_shape=(read_h, read_w),
                                     resampling=Resampling.bilinear).astype(np.float32)

                # Sample from tile_data for each masked pixel
                # Scale pixel coords to the read dimensions
                sample_cols = ((cols - c_min) * read_w / max(win_w, 1)).astype(int)
                sample_rows = ((rows - r_min) * read_h / max(win_h, 1)).astype(int)
                sample_cols = np.clip(sample_cols, 0, read_w - 1)
                sample_rows = np.clip(sample_rows, 0, read_h - 1)

                values = tile_data[sample_rows, sample_cols]

                # Handle nodata
                if ds.nodata is not None:
                    values[values == ds.nodata] = np.nan

                # Write valid values (overwrites overlapping areas - that's fine)
                valid_vals = ~np.isnan(values)
                flat_indices = np.where(mask.ravel())[0]
                valid_indices = flat_indices[valid_vals]
                output.ravel()[valid_indices] = values[valid_vals]
                tiles_used.append(tile["tile_id"])

            except Exception as e:
                logger.warning(f"Error reading tile {tile['tile_id']}: {e}")
                continue

        if not tiles_used:
            return None

        logger.info(f"LiDAR read_block: {out_w}x{out_h} px, {len(tiles_used)} tiles ({', '.join(tiles_used)}), res={actual_res:.1f}m")

        meta = {
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
            "width": out_w,
            "height": out_h,
            "resolution_m": round(actual_res, 2),
            "native_resolution_m": 1.0,
            "dataset": dataset_type,
            "tiles_used": tiles_used,
        }

        return output, meta

    def get_available_tiles(self) -> list[str]:
        """List available LiDAR tiles."""
        return [t["tile_id"] for t in self._tile_index]

    def get_status(self) -> dict:
        """Get LiDAR data status."""
        return {
            "available": len(self._tile_index) > 0,
            "mnt_tiles": len(self._tile_index),
            "mhc_tiles": sum(1 for t in self._tile_index if t["mhc_path"]),
            "tiles": [
                {
                    "id": t["tile_id"],
                    "bounds": t["bounds_wgs84"],
                    "has_canopy": t["mhc_path"] is not None,
                }
                for t in self._tile_index
            ],
            "resolution": "1m",
            "source": "MERN LiDAR (Données Québec)",
        }
