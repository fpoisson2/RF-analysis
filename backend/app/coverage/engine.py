"""
Coverage calculation engine.

Computes area coverage heatmaps and point-to-point path profiles.
Uses pre-loaded terrain grid + parallel azimuth sweep for speed.
GPU (CuPy) accelerates rendering.
"""
import io
import math
import time
import logging
from typing import Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from PIL import Image

from ..gpu import GPU_AVAILABLE, xp, to_numpy, to_gpu
from ..propagation.models import get_model, free_space
from ..propagation.diffraction import get_diffraction_model, fresnel_zone_radius
from ..antenna.patterns import get_pattern_by_type, get_antenna_gain
from ..terrain.srtm import SRTMManager, haversine_distance, destination_point, bearing

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Color schemas (5 dB steps)
# ═══════════════════════════════════════════════════════════════

COLOR_SCHEMAS = {
    "signal_strength": {
        "name": "Signal Strength (dBm)",
        "unit": "dBm",
        "stops": [
            (-30, (0, 60, 0, 230)),
            (-35, (0, 100, 0, 225)),
            (-40, (0, 140, 0, 220)),
            (-45, (0, 180, 0, 215)),
            (-50, (0, 210, 0, 210)),
            (-55, (80, 220, 0, 205)),
            (-60, (160, 230, 0, 200)),
            (-65, (210, 230, 0, 200)),
            (-70, (255, 230, 0, 195)),
            (-75, (255, 200, 0, 190)),
            (-80, (255, 165, 0, 185)),
            (-85, (255, 120, 0, 180)),
            (-90, (255, 80, 0, 175)),
            (-95, (255, 40, 0, 170)),
            (-100, (230, 0, 0, 165)),
            (-105, (200, 0, 40, 155)),
            (-110, (170, 0, 80, 150)),
            (-115, (140, 0, 120, 140)),
            (-120, (100, 0, 140, 130)),
            (-125, (70, 0, 130, 110)),
            (-130, (50, 0, 100, 90)),
        ],
    },
    "snr": {
        "name": "Signal to Noise Ratio (dB)",
        "unit": "dB",
        "stops": [
            (45, (0, 60, 0, 230)),
            (40, (0, 120, 0, 220)),
            (35, (0, 180, 0, 210)),
            (30, (60, 210, 0, 205)),
            (25, (160, 230, 0, 200)),
            (20, (255, 230, 0, 195)),
            (15, (255, 180, 0, 185)),
            (10, (255, 120, 0, 175)),
            (5, (230, 40, 0, 165)),
            (0, (180, 0, 60, 150)),
            (-5, (120, 0, 120, 130)),
            (-10, (60, 0, 100, 100)),
        ],
    },
    "path_loss": {
        "name": "Path Loss (dB)",
        "unit": "dB",
        "stops": [
            (50, (0, 60, 0, 230)),
            (60, (0, 140, 0, 220)),
            (70, (0, 210, 0, 210)),
            (80, (120, 230, 0, 200)),
            (90, (230, 230, 0, 195)),
            (100, (255, 190, 0, 185)),
            (110, (255, 140, 0, 180)),
            (120, (255, 80, 0, 170)),
            (130, (240, 20, 0, 160)),
            (140, (200, 0, 50, 150)),
            (150, (160, 0, 100, 140)),
            (160, (120, 0, 130, 130)),
            (170, (80, 0, 120, 110)),
            (180, (50, 0, 90, 90)),
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# Coverage Engine
# ═══════════════════════════════════════════════════════════════

class CoverageEngine:
    """Coverage calculation with pre-loaded terrain, parallel sweep, and GPU rendering."""

    def __init__(self, terrain_manager):
        self.terrain = terrain_manager
        if GPU_AVAILABLE:
            logger.info("CoverageEngine: GPU acceleration ENABLED")
        else:
            logger.info("CoverageEngine: Using CPU (NumPy)")

    def calculate_area(self, params: dict) -> dict:
        """
        Calculate area coverage heatmap with terrain + diffraction.

        Optimizations:
        1. Pre-load entire terrain grid in one block read (LiDAR or SRTM)
        2. Parallel azimuth sweep (ThreadPoolExecutor)
        3. Terrain profile lookup by numpy indexing (no rasterio per-point)
        """
        start_time = time.time()

        # ── Extract parameters ────────────────────────────────────
        tx = params["transmitter"]
        sig = params["signal"]
        feed = params["feeder"]
        ant = params["antenna"]
        rx = params["receiver"]
        mdl = params["model"]
        env = params["environment"]
        out = params["output"]

        tx_lat, tx_lon = tx["lat"], tx["lon"]
        tx_h = tx["height"]
        freq = sig["frequency"]
        power_w = sig["power"]
        bandwidth = sig["bandwidth"]
        feeder_loss = feed["loss"]
        ant_gain_dbi = ant["gain"]
        ant_azimuth = ant["azimuth"]
        ant_tilt = ant["tilt"]
        rx_h = rx["height"]
        rx_gain = rx["gain"]
        sensitivity = rx["sensitivity"]
        radius_km = out["radius"]
        resolution_m = out["resolution"]
        model_name = mdl["name"]
        diffraction_name = mdl.get("diffraction", "deygout94")
        reliability = mdl.get("reliability", 50)
        noise_floor = env.get("noise_floor", -100)
        units = out.get("units", "dBm")
        color_schema = out.get("color_schema", "signal_strength")
        use_canopy = env.get("elevation_model", "dtm") == "dsm"

        # ERP / EIRP
        erp_w = power_w * 10 ** ((ant_gain_dbi - 2.15 - feeder_loss) / 10)
        eirp_w = power_w * 10 ** ((ant_gain_dbi - feeder_loss) / 10)
        erp_dbm = 10 * math.log10(erp_w * 1000) if erp_w > 0 else -999
        eirp_dbm = 10 * math.log10(eirp_w * 1000) if eirp_w > 0 else -999
        tx_power_dbm = 10 * math.log10(power_w * 1000) if power_w > 0 else 0

        # Grid dimensions
        n_cells = int(2 * radius_km * 1000 / resolution_m)
        n_cells = max(10, min(n_cells, 2000))
        actual_resolution = 2 * radius_km * 1000 / n_cells

        cos_lat = math.cos(math.radians(tx_lat))
        lat_per_m = 1.0 / 111320.0
        lon_per_m = 1.0 / (111320.0 * cos_lat)
        half_lat = radius_km * 1000 * lat_per_m
        half_lon = radius_km * 1000 * lon_per_m

        lat_min = tx_lat - half_lat
        lat_max = tx_lat + half_lat
        lon_min = tx_lon - half_lon
        lon_max = tx_lon + half_lon

        # Models
        prop_model = get_model(model_name)
        diff_model = get_diffraction_model(diffraction_name)
        use_diffraction = diffraction_name != "none"

        # Antenna pattern
        pattern = get_pattern_by_type(
            ant.get("pattern_type", "dipole"),
            gain_dbi=ant_gain_dbi,
            h_beamwidth=ant.get("h_beamwidth", 360),
            v_beamwidth=ant.get("v_beamwidth", 90),
        )

        # ── Step 1: Pre-load terrain grid in one shot ─────────────
        t1 = time.time()

        # Try LiDAR block read first (fast, high-res)
        elev_grid = None
        terrain_source = "SRTM"
        ds_type = "mhc" if use_canopy else "mnt"

        if hasattr(self.terrain, 'read_block'):
            # Read at coverage resolution (no need for 1m here)
            terrain_res = max(actual_resolution, 5)  # At least 5m
            max_terrain_px = int(2 * radius_km * 1000 / terrain_res)
            max_terrain_px = min(max_terrain_px, 2000)

            block = self.terrain.read_block(
                lat_min, lon_min, lat_max, lon_max,
                dataset_type=ds_type, max_pixels=max_terrain_px
            )
            if block is not None:
                elev_grid = block[0]
                terrain_source = "LiDAR"

                # If using canopy mode but read MHC, we need terrain + canopy
                if use_canopy:
                    mnt_block = self.terrain.read_block(
                        lat_min, lon_min, lat_max, lon_max,
                        dataset_type="mnt", max_pixels=max_terrain_px
                    )
                    if mnt_block is not None:
                        mnt_data = mnt_block[0]
                        if mnt_data.shape == elev_grid.shape:
                            elev_grid = mnt_data + np.maximum(elev_grid, 0)
                        else:
                            # Just use MNT if shapes don't match
                            elev_grid = mnt_data

        # Fallback to point-by-point if no block read
        if elev_grid is None:
            terrain_n = min(500, n_cells)
            elev_grid = np.zeros((terrain_n, terrain_n), dtype=np.float32)
            t_lats = np.linspace(lat_max, lat_min, terrain_n)
            t_lons = np.linspace(lon_min, lon_max, terrain_n)
            for r in range(terrain_n):
                for c in range(terrain_n):
                    elev_grid[r, c] = self.terrain.get_elevation(t_lats[r], t_lons[c])

        elev_grid = np.nan_to_num(elev_grid, nan=0.0)
        terrain_h, terrain_w = elev_grid.shape

        t_terrain = (time.time() - t1) * 1000
        logger.info(f"Coverage: {n_cells}x{n_cells} @ {actual_resolution:.0f}m | Terrain: {terrain_w}x{terrain_h} [{terrain_source}] {t_terrain:.0f}ms")

        # ── Helper: sample terrain from pre-loaded grid ───────────
        def sample_elevation(lat, lon):
            """Fast elevation lookup from pre-loaded grid."""
            r = int((lat_max - lat) / (lat_max - lat_min) * (terrain_h - 1))
            c = int((lon - lon_min) / (lon_max - lon_min) * (terrain_w - 1))
            r = max(0, min(terrain_h - 1, r))
            c = max(0, min(terrain_w - 1, c))
            return float(elev_grid[r, c])

        # ── Step 2: Grid-based coverage with terrain profiles ─────
        t2 = time.time()

        # Pre-compute noise for SNR mode
        johnson_noise = -174.0 + 10 * math.log10(bandwidth * 1e6) if bandwidth > 0 else -174
        effective_noise = max(noise_floor, johnson_noise)

        # Output grid
        grid = np.full((n_cells, n_cells), np.nan, dtype=np.float32)

        # For each pixel: compute distance, azimuth, then propagation
        # Vectorized distance/azimuth computation
        center = n_cells // 2
        rows_idx = np.arange(n_cells)
        cols_idx = np.arange(n_cells)
        rr, cc = np.meshgrid(rows_idx, cols_idx, indexing='ij')

        # Lat/lon of each pixel
        pixel_lats = lat_max - rr * (lat_max - lat_min) / n_cells
        pixel_lons = lon_min + cc * (lon_max - lon_min) / n_cells

        # Distance from TX in km
        dlat_m = (pixel_lats - tx_lat) * 111320
        dlon_m = (pixel_lons - tx_lon) * 111320 * cos_lat
        dist_m = np.sqrt(dlat_m**2 + dlon_m**2)
        dist_km = dist_m / 1000.0
        dist_km_clipped = np.maximum(dist_km, 0.001)

        # Azimuth from TX (degrees)
        az_grid = np.degrees(np.arctan2(dlon_m, dlat_m)) % 360

        # Circular mask
        radius_m_val = radius_km * 1000
        circle_mask = dist_m <= radius_m_val

        # Vectorized propagation (no terrain profile - base loss)
        base_path_loss = prop_model(dist_km_clipped, freq, tx_h, rx_h, reliability=reliability)
        base_path_loss = np.asarray(base_path_loss, dtype=np.float32)

        # Vectorized antenna gain (lookup from pattern)
        az_idx = (az_grid.astype(int) % 360).ravel()
        ant_gains = np.array([pattern[a, 90] for a in az_idx], dtype=np.float32).reshape(n_cells, n_cells)

        # Base link budget (vectorized)
        rx_power = tx_power_dbm - feeder_loss + ant_gains - base_path_loss + rx_gain

        # Now add terrain diffraction correction via radial sampling
        # Use fewer azimuths but sample each properly
        n_azimuths = 720
        n_profile_pts = min(40, max(8, int(radius_km * 1.5)))

        # For each azimuth, compute diffraction loss along a ray,
        # then apply it to all pixels near that azimuth
        diff_grid = np.zeros((n_cells, n_cells), dtype=np.float32)

        if use_diffraction:
            for az_i in range(n_azimuths):
                az_deg = az_i * 360.0 / n_azimuths
                az_rad = math.radians(az_deg)

                # End point of ray
                end_lat = tx_lat + math.cos(az_rad) * half_lat * 2 * (radius_km * 1000) / (2 * radius_km * 1000)
                end_lon = tx_lon + math.sin(az_rad) * half_lon * 2 * (radius_km * 1000) / (2 * radius_km * 1000)

                # Terrain profile from pre-loaded grid
                p_rows = np.linspace(center, center - math.cos(az_rad) * center, n_profile_pts).astype(int)
                p_cols = np.linspace(center, center + math.sin(az_rad) * center, n_profile_pts).astype(int)
                p_rows = np.clip(p_rows, 0, terrain_h - 1)
                p_cols = np.clip(p_cols, 0, terrain_w - 1)
                profile_h = elev_grid[p_rows, p_cols]
                profile_d = np.linspace(0, radius_km * 1000, n_profile_pts)

                # Compute cumulative diffraction loss along this ray
                ray_diff = np.zeros(n_profile_pts)
                for p_i in range(2, n_profile_pts):
                    sub_h = profile_h[:p_i+1]
                    sub_d = profile_d[:p_i+1]
                    try:
                        ray_diff[p_i] = float(diff_model(sub_d, sub_h, tx_h, rx_h, freq))
                    except Exception:
                        ray_diff[p_i] = ray_diff[p_i-1]

                # Apply to pixels in this azimuth slice
                az_low = (az_deg - 360.0 / n_azimuths / 2) % 360
                az_high = (az_deg + 360.0 / n_azimuths / 2) % 360

                if az_low < az_high:
                    az_mask = (az_grid >= az_low) & (az_grid < az_high) & circle_mask
                else:  # Wraps around 0/360
                    az_mask = ((az_grid >= az_low) | (az_grid < az_high)) & circle_mask

                if np.any(az_mask):
                    # Map pixel distance to profile index
                    pixel_frac = dist_m[az_mask] / radius_m_val
                    pixel_prof_idx = np.clip((pixel_frac * (n_profile_pts - 1)).astype(int), 0, n_profile_pts - 1)
                    diff_grid[az_mask] = ray_diff[pixel_prof_idx]

        # Apply diffraction to link budget
        rx_power -= diff_grid

        # Apply units and threshold
        if units == "dB":
            output_values = rx_power - effective_noise
            grid = np.where(circle_mask & (output_values >= sensitivity), output_values, np.nan)
        elif units == "dBuV":
            output_values = rx_power + 90 + 20 * math.log10(50)
            grid = np.where(circle_mask & (rx_power >= sensitivity), output_values, np.nan)
        else:
            grid = np.where(circle_mask & (rx_power >= sensitivity), rx_power, np.nan)

        t_sweep = (time.time() - t2) * 1000
        logger.info(f"  Compute ({n_azimuths} diffraction rays): {t_sweep:.0f}ms")

        # ── Step 3: Render heatmap ────────────────────────────────
        t3 = time.time()
        image_data = self._render_heatmap(grid, color_schema)
        t_render = (time.time() - t3) * 1000

        # Stats
        valid_cells = int(np.count_nonzero(~np.isnan(grid)))
        total_cells = n_cells * n_cells
        coverage_pct = valid_cells / total_cells * 100
        elapsed = (time.time() - start_time) * 1000

        logger.info(f"  Render: {t_render:.0f}ms | TOTAL: {elapsed:.0f}ms | Coverage: {coverage_pct:.1f}%")

        bounds = {
            "north": lat_max, "south": lat_min,
            "east": lon_max, "west": lon_min,
        }

        return {
            "image_data": image_data,
            "bounds": bounds,
            "stats": {
                "coverage_pct": round(coverage_pct, 1),
                "valid_cells": valid_cells,
                "total_cells": total_cells,
                "grid_size": n_cells,
                "resolution_m": round(actual_resolution, 1),
                "megapixels": round(total_cells / 1e6, 2),
                "min_signal": round(float(np.nanmin(grid)), 1) if valid_cells > 0 else None,
                "max_signal": round(float(np.nanmax(grid)), 1) if valid_cells > 0 else None,
                "mean_signal": round(float(np.nanmean(grid)), 1) if valid_cells > 0 else None,
                "gpu": GPU_AVAILABLE,
                "terrain_source": terrain_source,
                "timings_ms": {
                    "terrain_load": round(t_terrain),
                    "radial_sweep": round(t_sweep),
                    "render": round(t_render),
                    "total": round(elapsed),
                },
            },
            "erp_w": round(erp_w, 4),
            "erp_dbm": round(erp_dbm, 1),
            "eirp_w": round(eirp_w, 4),
            "eirp_dbm": round(eirp_dbm, 1),
        }

    def calculate_path(self, params: dict) -> dict:
        """Calculate point-to-point path profile."""
        tx = params["transmitter"]
        rx = params["receiver"]
        sig = params["signal"]
        feed = params["feeder"]
        ant = params["antenna"]
        mdl = params["model"]

        if rx.get("lat") is None or rx.get("lon") is None:
            raise ValueError("Receiver coordinates required for path profile")

        freq = sig["frequency"]
        tx_h = tx["height"]
        rx_h = rx["height"]
        power_w = sig["power"]
        feeder_loss = feed["loss"]
        ant_gain = ant["gain"]
        rx_gain = rx["gain"]
        tx_power_dbm = 10 * math.log10(power_w * 1000) if power_w > 0 else 0

        num_points = 200
        distances, elevations = self.terrain.get_profile(
            tx["lat"], tx["lon"], rx["lat"], rx["lon"], num_points
        )

        d_total = distances[-1]
        prop_model = get_model(mdl["name"])

        signal_levels = np.zeros(num_points)
        fresnel_clearance = np.zeros(num_points)
        los_clearance = np.zeros(num_points)

        tx_elev = elevations[0] + tx_h
        rx_elev = elevations[-1] + rx_h

        for i in range(num_points):
            d_m = distances[i]
            d_km = d_m / 1000.0
            if d_km < 0.001:
                signal_levels[i] = tx_power_dbm
                continue

            path_loss = float(np.atleast_1d(prop_model(d_km, freq, tx_h, rx_h))[0])
            signal_levels[i] = tx_power_dbm - feeder_loss + ant_gain - path_loss + rx_gain

            los_height = tx_elev + (rx_elev - tx_elev) * d_m / d_total
            los_clearance[i] = los_height - elevations[i]

            d_from_rx = d_total - d_m
            if d_m > 0 and d_from_rx > 0:
                f1_radius = fresnel_zone_radius(d_m, d_from_rx, freq)
                fresnel_clearance[i] = (los_height - elevations[i]) / f1_radius if f1_radius > 0 else 0

        path_bearing = bearing(tx["lat"], tx["lon"], rx["lat"], rx["lon"])

        return {
            "distances": distances.tolist(),
            "elevations": elevations.tolist(),
            "signal_levels": signal_levels.tolist(),
            "fresnel_clearance": fresnel_clearance.tolist(),
            "los_clearance": los_clearance.tolist(),
            "stats": {
                "distance_km": round(d_total / 1000, 2),
                "bearing_deg": round(path_bearing, 1),
                "tx_elevation": round(float(elevations[0]), 1),
                "rx_elevation": round(float(elevations[-1]), 1),
                "max_elevation": round(float(np.max(elevations)), 1),
                "min_elevation": round(float(np.min(elevations)), 1),
                "signal_at_rx": round(float(signal_levels[-1]), 1),
                "free_space_loss": round(float(free_space(d_total / 1000, freq)), 1),
            },
        }

    def _render_heatmap(self, grid: np.ndarray, schema_name: str) -> bytes:
        """Render coverage grid as PNG. Vectorized color mapping."""
        h, w = grid.shape
        image = np.zeros((h, w, 4), dtype=np.uint8)

        schema = COLOR_SCHEMAS.get(schema_name, COLOR_SCHEMAS["signal_strength"])
        stops = schema["stops"]
        valid = ~np.isnan(grid)

        # Top stop
        top_mask = valid & (grid >= stops[0][0])
        if np.any(top_mask):
            image[top_mask] = stops[0][1]

        # Interpolate between stops
        for i in range(len(stops) - 1):
            v_high, c_high = stops[i]
            v_low, c_low = stops[i + 1]
            mask = valid & (grid >= v_low) & (grid < v_high)
            if not np.any(mask):
                continue
            t = (grid[mask] - v_low) / max(v_high - v_low, 0.01)
            image[mask, 0] = np.clip(c_low[0] + t * (c_high[0] - c_low[0]), 0, 255).astype(np.uint8)
            image[mask, 1] = np.clip(c_low[1] + t * (c_high[1] - c_low[1]), 0, 255).astype(np.uint8)
            image[mask, 2] = np.clip(c_low[2] + t * (c_high[2] - c_low[2]), 0, 255).astype(np.uint8)
            image[mask, 3] = np.clip(c_low[3] + t * (c_high[3] - c_low[3]), 0, 255).astype(np.uint8)

        img = Image.fromarray(image, "RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
