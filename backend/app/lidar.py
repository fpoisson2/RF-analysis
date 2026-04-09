"""
LiDAR data processor for high-resolution terrain and surface models.

Supports:
- LAS/LAZ point cloud files
- Generation of DTM (bare earth) and DSM (surface including buildings/trees)
- Building height extraction (DSM - DTM)
- Canopy height model (CHM) for vegetation
- Configurable resolution output

Typical Quebec LiDAR: 4 pts/m^2 → supports 0.5m resolution
"""
import os
import logging
import struct
from pathlib import Path
from typing import Optional, Tuple
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

# Try to import laspy for LAS/LAZ file reading
try:
    import laspy
    HAS_LASPY = True
except ImportError:
    HAS_LASPY = False
    logger.info("laspy not installed. Install with: pip install laspy[lazrs]")

# Try to import rasterio for GeoTIFF reading
try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    logger.info("rasterio not installed. Install with: pip install rasterio")


# LAS point classification codes (ASPRS standard)
CLASS_UNCLASSIFIED = 1
CLASS_GROUND = 2
CLASS_LOW_VEGETATION = 3
CLASS_MEDIUM_VEGETATION = 4
CLASS_HIGH_VEGETATION = 5
CLASS_BUILDING = 6
CLASS_NOISE = 7
CLASS_WATER = 9
CLASS_BRIDGE = 17


class LiDARProcessor:
    """Process LiDAR data for RF planning."""

    def __init__(self, data_dir: str, default_resolution: float = 2.0):
        self.data_dir = Path(data_dir)
        self.lidar_dir = self.data_dir / "lidar"
        self.cache_dir = self.data_dir / "lidar_cache"
        self.lidar_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_resolution = default_resolution

    def process_las_file(self, filepath: str, resolution: float = None) -> dict:
        """
        Process a LAS/LAZ file and generate DTM, DSM, and CHM rasters.

        Args:
            filepath: Path to .las or .laz file
            resolution: Output resolution in meters (default: 2.0m)

        Returns:
            dict with 'dtm', 'dsm', 'chm', 'buildings' numpy arrays and metadata
        """
        if not HAS_LASPY:
            raise ImportError("laspy is required. Install with: pip install laspy[lazrs]")

        resolution = resolution or self.default_resolution
        filepath = Path(filepath)

        # Check cache
        cache_key = f"{filepath.stem}_r{resolution}"
        dtm_cache = self.cache_dir / f"{cache_key}_dtm.npy"
        dsm_cache = self.cache_dir / f"{cache_key}_dsm.npy"
        meta_cache = self.cache_dir / f"{cache_key}_meta.npy"

        if dtm_cache.exists() and dsm_cache.exists() and meta_cache.exists():
            logger.info(f"Loading cached LiDAR data: {cache_key}")
            dtm = np.load(dtm_cache)
            dsm = np.load(dsm_cache)
            meta = np.load(meta_cache, allow_pickle=True).item()
            chm = dsm - dtm
            chm[chm < 0] = 0
            return {"dtm": dtm, "dsm": dsm, "chm": chm, "meta": meta}

        logger.info(f"Processing LiDAR file: {filepath} at {resolution}m resolution")

        # Read LAS/LAZ file
        las = laspy.read(str(filepath))
        logger.info(f"  Points: {len(las.points):,}")
        logger.info(f"  Point density: ~{len(las.points) / ((las.header.x_max - las.header.x_min) * (las.header.y_max - las.header.y_min)):.1f} pts/m²")

        x = np.array(las.x)
        y = np.array(las.y)
        z = np.array(las.z)
        classifications = np.array(las.classification)

        # Compute grid dimensions
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()
        cols = int(np.ceil((x_max - x_min) / resolution))
        rows = int(np.ceil((y_max - y_min) / resolution))

        logger.info(f"  Grid: {cols} x {rows} ({cols * rows:,} cells)")
        logger.info(f"  Extent: {x_min:.1f}-{x_max:.1f} E, {y_min:.1f}-{y_max:.1f} N")

        # Grid indices for each point
        col_idx = np.clip(((x - x_min) / resolution).astype(int), 0, cols - 1)
        row_idx = np.clip(((y_max - y) / resolution).astype(int), 0, rows - 1)

        # ── DTM: Ground only (class 2) ─────────────────────────────
        ground_mask = classifications == CLASS_GROUND
        dtm = self._grid_min(z, row_idx, col_idx, rows, cols, ground_mask)
        # Fill gaps with interpolation
        dtm = self._fill_gaps(dtm)

        # ── DSM: All points (highest point per cell) ───────────────
        valid_mask = (classifications != CLASS_NOISE)
        dsm = self._grid_max(z, row_idx, col_idx, rows, cols, valid_mask)
        # Fill gaps
        dsm = self._fill_gaps(dsm)

        # DSM should never be below DTM
        dsm = np.maximum(dsm, dtm)

        # ── CHM: Canopy Height Model ──────────────────────────────
        chm = dsm - dtm
        chm[chm < 0] = 0

        # ── Building heights ──────────────────────────────────────
        building_mask = classifications == CLASS_BUILDING
        buildings = self._grid_max(z, row_idx, col_idx, rows, cols, building_mask)
        buildings = buildings - dtm
        buildings[buildings < 0] = 0
        buildings[np.isnan(buildings)] = 0

        # Metadata
        meta = {
            "x_min": float(x_min),
            "x_max": float(x_max),
            "y_min": float(y_min),
            "y_max": float(y_max),
            "resolution": resolution,
            "rows": rows,
            "cols": cols,
            "crs": str(las.header.parse_crs()) if hasattr(las.header, 'parse_crs') else "unknown",
            "point_count": len(las.points),
        }

        # Cache results
        np.save(dtm_cache, dtm)
        np.save(dsm_cache, dsm)
        np.save(meta_cache, meta)

        logger.info(f"  DTM range: {np.nanmin(dtm):.1f} - {np.nanmax(dtm):.1f} m")
        logger.info(f"  DSM range: {np.nanmin(dsm):.1f} - {np.nanmax(dsm):.1f} m")
        logger.info(f"  Max building height: {np.nanmax(buildings):.1f} m")
        logger.info(f"  Max canopy height: {np.nanmax(chm):.1f} m")

        return {
            "dtm": dtm,
            "dsm": dsm,
            "chm": chm,
            "buildings": buildings,
            "meta": meta,
        }

    def read_geotiff(self, filepath: str) -> Tuple[np.ndarray, dict]:
        """
        Read a GeoTIFF file (DTM or DSM).
        Used for pre-processed LiDAR products from Données Québec.
        """
        if not HAS_RASTERIO:
            raise ImportError("rasterio is required. Install with: pip install rasterio")

        with rasterio.open(filepath) as src:
            data = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan

            meta = {
                "x_min": src.bounds.left,
                "x_max": src.bounds.right,
                "y_min": src.bounds.bottom,
                "y_max": src.bounds.top,
                "resolution": src.res[0],
                "rows": src.height,
                "cols": src.width,
                "crs": str(src.crs),
            }

        return data, meta

    def get_elevation_at(self, grid: np.ndarray, meta: dict,
                          x: float, y: float) -> float:
        """Get elevation from a grid at a specific coordinate."""
        col = int((x - meta["x_min"]) / meta["resolution"])
        row = int((meta["y_max"] - y) / meta["resolution"])

        if 0 <= row < meta["rows"] and 0 <= col < meta["cols"]:
            val = grid[row, col]
            return float(val) if not np.isnan(val) else 0.0
        return 0.0

    def get_profile_from_grid(self, grid: np.ndarray, meta: dict,
                               x1: float, y1: float, x2: float, y2: float,
                               num_points: int = 100) -> Tuple[np.ndarray, np.ndarray]:
        """Extract elevation profile from a grid along a line."""
        xs = np.linspace(x1, x2, num_points)
        ys = np.linspace(y1, y2, num_points)

        cols = np.clip(((xs - meta["x_min"]) / meta["resolution"]).astype(int),
                       0, meta["cols"] - 1)
        rows = np.clip(((meta["y_max"] - ys) / meta["resolution"]).astype(int),
                       0, meta["rows"] - 1)

        elevations = grid[rows, cols]
        distances = np.sqrt((xs - x1) ** 2 + (ys - y1) ** 2) * meta["resolution"]

        return distances, elevations

    def _grid_min(self, z, rows, cols, n_rows, n_cols, mask=None):
        """Create grid with minimum z value per cell."""
        grid = np.full((n_rows, n_cols), np.nan, dtype=np.float32)

        if mask is not None:
            z = z[mask]
            rows = rows[mask]
            cols = cols[mask]

        if len(z) == 0:
            return grid

        # Use numpy advanced indexing
        linear_idx = rows * n_cols + cols
        # Sort by z to get minimum per cell
        sort_order = np.argsort(-z)  # Descending so last write wins (minimum)
        z_sorted = z[sort_order]
        idx_sorted = linear_idx[sort_order]
        grid_flat = grid.ravel()
        grid_flat[idx_sorted] = z_sorted
        # Now we need actual minimum - use bincount
        grid = np.full((n_rows, n_cols), np.nan, dtype=np.float32)
        for i in range(len(z)):
            r, c = rows[i], cols[i]
            if np.isnan(grid[r, c]) or z[i] < grid[r, c]:
                grid[r, c] = z[i]

        return grid

    def _grid_max(self, z, rows, cols, n_rows, n_cols, mask=None):
        """Create grid with maximum z value per cell."""
        grid = np.full((n_rows, n_cols), np.nan, dtype=np.float32)

        if mask is not None:
            z = z[mask]
            rows = rows[mask]
            cols = cols[mask]

        if len(z) == 0:
            return grid

        for i in range(len(z)):
            r, c = rows[i], cols[i]
            if np.isnan(grid[r, c]) or z[i] > grid[r, c]:
                grid[r, c] = z[i]

        return grid

    def _fill_gaps(self, grid: np.ndarray, max_gap: int = 5) -> np.ndarray:
        """Fill NaN gaps in a grid using nearest neighbor interpolation."""
        from scipy.ndimage import distance_transform_edt

        mask = np.isnan(grid)
        if not mask.any():
            return grid

        try:
            # Use scipy for gap filling
            indices = distance_transform_edt(mask, return_distances=False, return_indices=True)
            filled = grid[tuple(indices)]
            return filled
        except ImportError:
            # Fallback: simple filling with mean of neighbors
            filled = grid.copy()
            for _ in range(max_gap):
                for r in range(1, grid.shape[0] - 1):
                    for c in range(1, grid.shape[1] - 1):
                        if np.isnan(filled[r, c]):
                            neighbors = filled[r-1:r+2, c-1:c+2]
                            valid = neighbors[~np.isnan(neighbors)]
                            if len(valid) > 0:
                                filled[r, c] = valid.mean()
            return filled

    def list_available_files(self) -> list[dict]:
        """List available LiDAR files in the data directory."""
        files = []
        for ext in ["*.las", "*.laz", "*.tif", "*.tiff"]:
            for f in self.lidar_dir.glob(ext):
                files.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": f.stat().st_size / 1e6,
                    "format": f.suffix,
                })
        return files
