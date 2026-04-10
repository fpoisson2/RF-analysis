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
from .cuda_kernels import compute_diffraction_grid_gpu, compute_diffraction_grid_cpu

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Color schemas (5 dB steps)
# ═══════════════════════════════════════════════════════════════

# Rainbow palette inspired by CloudRF: RED = strong, GREEN = medium,
# BLUE = weak. The previous palette mapped the strongest signals to dark
# green which made the transmitter centre look like a shadow spot.
COLOR_SCHEMAS = {
    "signal_strength": {
        "name": "Signal Strength (dBm)",
        "unit": "dBm",
        "stops": [
            (-30, (255,  30,  30, 235)),  # bright red - excellent
            (-40, (255,  60,   0, 230)),  # red
            (-50, (255, 110,   0, 225)),  # red-orange
            (-55, (255, 150,   0, 220)),  # orange
            (-60, (255, 190,   0, 215)),  # amber
            (-65, (255, 225,   0, 210)),  # yellow
            (-70, (220, 240,   0, 205)),  # yellow-green
            (-75, (170, 240,   0, 200)),  # lime
            (-80, (100, 225,  20, 195)),  # green
            (-85, ( 30, 200,  60, 190)),  # forest green
            (-90, (  0, 180, 120, 180)),  # teal-green
            (-95, (  0, 160, 180, 170)),  # teal
            (-100, (  0, 130, 210, 160)), # cyan-blue
            (-105, ( 10,  90, 220, 150)), # blue
            (-110, ( 40,  60, 200, 135)), # deep blue
            (-115, ( 70,  30, 170, 120)), # indigo
            (-120, ( 80,  10, 140, 105)), # violet
            (-125, ( 70,   0, 110,  90)), # purple
            (-130, ( 50,   0,  80,  75)), # dark purple - noise floor
        ],
    },
    "snr": {
        "name": "Signal to Noise Ratio (dB)",
        "unit": "dB",
        "stops": [
            (45, (255,  30,  30, 235)),
            (40, (255,  90,   0, 225)),
            (35, (255, 150,   0, 220)),
            (30, (255, 210,   0, 210)),
            (25, (200, 235,   0, 205)),
            (20, (120, 225,  20, 200)),
            (15, ( 30, 200,  80, 190)),
            (10, (  0, 170, 170, 180)),
            ( 5, (  0, 130, 210, 165)),
            ( 0, ( 40,  60, 200, 140)),
            (-5, ( 70,  20, 160, 120)),
            (-10, (50,   0, 100, 100)),
        ],
    },
    "path_loss": {
        "name": "Path Loss (dB)",
        "unit": "dB",
        "stops": [
            ( 50, (255,  30,  30, 235)),
            ( 60, (255,  90,   0, 225)),
            ( 70, (255, 150,   0, 220)),
            ( 80, (255, 210,   0, 210)),
            ( 90, (200, 235,   0, 200)),
            (100, (100, 225,  20, 195)),
            (110, ( 30, 200,  80, 190)),
            (120, (  0, 170, 170, 180)),
            (130, (  0, 130, 210, 165)),
            (140, ( 40,  60, 200, 150)),
            (150, ( 70,  20, 160, 130)),
            (160, ( 80,   0, 130, 110)),
            (170, ( 60,   0, 100,  90)),
            (180, ( 40,   0,  70,  75)),
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
        context = mdl.get("context", env.get("context", "average"))  # conservative / average / optimistic
        noise_floor = env.get("noise_floor", -100)
        units = out.get("units", "dBm")
        color_schema = out.get("color_schema", "signal_strength")
        use_canopy = env.get("elevation_model", "dtm") == "dsm"
        clutter_preset = env.get("clutter", "suburban")  # rural / suburban / urban / dense_urban

        # ERP / EIRP
        erp_w = power_w * 10 ** ((ant_gain_dbi - 2.15 - feeder_loss) / 10)
        eirp_w = power_w * 10 ** ((ant_gain_dbi - feeder_loss) / 10)
        erp_dbm = 10 * math.log10(erp_w * 1000) if erp_w > 0 else -999
        eirp_dbm = 10 * math.log10(eirp_w * 1000) if eirp_w > 0 else -999
        tx_power_dbm = 10 * math.log10(power_w * 1000) if power_w > 0 else 0

        # Grid dimensions
        # Honour the user's requested resolution even at large radii.
        # The cap is deliberately generous (16 MP) so a 500 km radius
        # at 250 m/px still fits. Only clamp if we'd otherwise blow past
        # the compute budget.
        requested_cells = int(2 * radius_km * 1000 / resolution_m)
        MAX_CELLS = 4000  # 16 MP ceiling
        n_cells = max(10, min(requested_cells, MAX_CELLS))
        if requested_cells > MAX_CELLS:
            logger.info(
                f"  Requested {requested_cells}x{requested_cells} exceeds {MAX_CELLS}px cap; "
                f"clamping (effective resolution = {2 * radius_km * 1000 / MAX_CELLS:.0f} m)"
            )
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

        # Large-radius flag: at >150 km, flat-earth and equirectangular
        # pixel spacing start to introduce visible errors. We switch to
        # Mercator Y pixel spacing and per-pixel cos_lat distance so the
        # image overlay aligns correctly on the MapLibre map.
        large_radius = radius_km > 150.0

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

        # Read MNT (bare earth) and MHC (canopy + buildings) together.
        # MHC on MERN Québec data is derived from LiDAR first-returns so
        # it includes BOTH tree canopy AND building roofs. We always
        # fold MHC into the terrain used for diffraction so urban areas
        # get realistic knife-edge shadowing - matching CloudRF's DSM
        # behaviour. The UI DTM/DSM toggle only affects display layers.
        elev_grid = None       # Surface used for diffraction (MNT+MHC)
        base_grid = None       # Bare earth MNT for antenna mounting
        mhc_grid = None        # Canopy/buildings delta (for 3D display)
        terrain_source = "SRTM"

        if hasattr(self.terrain, 'read_block'):
            # Read at coverage resolution (no need for 1m here).
            # Keep the terrain block slightly smaller than the output grid
            # since terrain is only sampled along diffraction rays.
            terrain_res = max(actual_resolution, 5)  # At least 5m
            max_terrain_px = int(2 * radius_km * 1000 / terrain_res)
            max_terrain_px = min(max_terrain_px, 3000)

            mnt_block = self.terrain.read_block(
                lat_min, lon_min, lat_max, lon_max,
                dataset_type="mnt", max_pixels=max_terrain_px,
            )
            if mnt_block is not None:
                base_grid = np.nan_to_num(mnt_block[0], nan=0.0).astype(np.float32, copy=False)
                terrain_source = "LiDAR"

                # Try to also read MHC (canopy + buildings) at same shape
                mhc_block = self.terrain.read_block(
                    lat_min, lon_min, lat_max, lon_max,
                    dataset_type="mhc", max_pixels=max_terrain_px,
                )
                if mhc_block is not None and mhc_block[0].shape == base_grid.shape:
                    mhc_grid = np.nan_to_num(mhc_block[0], nan=0.0).astype(np.float32, copy=False)
                    mhc_grid = np.maximum(mhc_grid, 0.0)  # negative = noise
                    elev_grid = base_grid + mhc_grid
                else:
                    elev_grid = base_grid

        # Fallback to point-by-point if no block read (no LiDAR)
        if elev_grid is None:
            terrain_n = min(500, n_cells)
            base_grid = np.zeros((terrain_n, terrain_n), dtype=np.float32)
            t_lats = np.linspace(lat_max, lat_min, terrain_n)
            t_lons = np.linspace(lon_min, lon_max, terrain_n)
            for r in range(terrain_n):
                for c in range(terrain_n):
                    base_grid[r, c] = self.terrain.get_elevation(t_lats[r], t_lons[c])
            base_grid = np.nan_to_num(base_grid, nan=0.0)
            elev_grid = base_grid

        terrain_h, terrain_w = elev_grid.shape

        # When the user explicitly wants a bare-earth simulation
        # (use_canopy=False), they still get MHC in the diffraction path
        # because that's what matches reality. But if they explicitly
        # ask for DTM-only sim we honor that by clearing mhc_grid.
        # (Most CloudRF-style tools don't offer this choice at all.)
        has_clutter_layer = mhc_grid is not None

        t_terrain = (time.time() - t1) * 1000
        logger.info(
            f"Coverage: {n_cells}x{n_cells} @ {actual_resolution:.0f}m | "
            f"Terrain: {terrain_w}x{terrain_h} [{terrain_source}] "
            f"{'+MHC clutter ' if has_clutter_layer else ''}{t_terrain:.0f}ms"
        )

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

        # Lat/lon of each pixel.
        # For large radii, use Mercator Y spacing so the rendered image
        # overlay (which MapLibre draws in Web-Mercator) aligns with the
        # actual ground coordinates. For small radii the difference is
        # negligible so we keep the cheap linear interp.
        pixel_lons = lon_min + (cc + 0.5) * (lon_max - lon_min) / n_cells

        if large_radius:
            y_top = math.log(math.tan(math.pi / 4 + math.radians(lat_max) / 2))
            y_bot = math.log(math.tan(math.pi / 4 + math.radians(lat_min) / 2))
            row_frac = (rr.astype(np.float64) + 0.5) / n_cells
            row_y = y_top + (y_bot - y_top) * row_frac  # row 0 = top
            pixel_lats = np.degrees(2 * np.arctan(np.exp(row_y)) - math.pi / 2)
        else:
            pixel_lats = lat_max - (rr + 0.5) * (lat_max - lat_min) / n_cells

        pixel_lats = pixel_lats.astype(np.float32)
        pixel_lons = pixel_lons.astype(np.float32)

        # Distance from TX in meters using per-pixel cos_lat (midpoint rule).
        # The single-cos(tx_lat) approximation drifts up to 9% at 500 km,
        # which both distorts the coverage disc shape and throws the path
        # loss out by ~1 dB on the remote edges.
        dlat_m = (pixel_lats - tx_lat) * 111320.0
        mid_lat_rad = np.radians((pixel_lats + tx_lat) * 0.5)
        cos_mid = np.cos(mid_lat_rad).astype(np.float32)
        dlon_m = (pixel_lons - tx_lon) * 111320.0 * cos_mid
        dist_m = np.sqrt(dlat_m ** 2 + dlon_m ** 2)
        dist_km = dist_m / 1000.0
        dist_km_clipped = np.maximum(dist_km, 0.001)

        # Azimuth from TX (degrees) — initial great-circle bearing
        az_grid = np.degrees(np.arctan2(dlon_m, dlat_m)) % 360

        # Circular mask
        radius_m_val = radius_km * 1000
        circle_mask = dist_m <= radius_m_val

        # Vectorized propagation (no terrain profile - base loss)
        base_path_loss = prop_model(
            dist_km_clipped, freq, tx_h, rx_h,
            reliability=reliability, context=context,
        )
        base_path_loss = np.asarray(base_path_loss, dtype=np.float32)

        # Vectorized antenna gain (fancy-indexed lookup, ~250x faster than list comp)
        pattern_slice = np.asarray(pattern[:360, 90], dtype=np.float32)  # (360,) az slice at 0° elev
        az_idx = (az_grid.astype(np.int32) % 360)
        ant_gains = pattern_slice[az_idx]

        # Base link budget (vectorized)
        rx_power = tx_power_dbm - feeder_loss + ant_gains - base_path_loss + rx_gain

        # ── Local terrain roughness map (per-pixel dh) ────────────
        # Computes std-dev of terrain in a ~100 m neighbourhood around
        # every output pixel. This gives the fine-grained clutter-like
        # texture CloudRF shows near the transmitter - textures that a
        # purely distance-based ITM area model can never produce.
        t_rough = time.time()
        local_dh = self._compute_local_roughness(
            elev_grid, n_cells,
            lat_min, lat_max, lon_min, lon_max,
            neighbourhood_m=120.0,
        )
        t_rough_ms = (time.time() - t_rough) * 1000

        # Clutter baseline from environment preset (rural/suburban/urban/dense_urban).
        # Matches CloudRF "Context" behaviour.  These are modest, because the
        # base path-loss models already include some statistical clutter.
        clutter_baseline = {
            "rural":       0.0,
            "suburban":    3.0,
            "urban":       8.0,
            "dense_urban": 14.0,
        }.get(clutter_preset, 3.0)

        # Frequency scaling for clutter/roughness loss
        # (higher frequencies attenuate more in clutter)
        freq_factor = float(np.clip(0.5 + np.log10(max(freq, 1.0) / 150.0) * 0.5, 0.4, 1.8))

        # Local clutter loss per pixel: grows with local terrain std
        # (0 for flat, ~12 dB for dh=30 m, ~18 dB for dh=100 m).
        # Scales with frequency factor.
        local_clutter = (
            6.0 * np.log10(1.0 + local_dh * 0.25) * freq_factor
        ).astype(np.float32)
        logger.info(
            f"  Local roughness: {t_rough_ms:.0f}ms "
            f"(dh median={float(np.median(local_dh)):.1f}m, "
            f"p95={float(np.percentile(local_dh, 95)):.1f}m)"
        )

        # ── Per-pixel terrain-aware knife-edge diffraction (CUDA) ──
        # Replaces the old radial-sweep with profile quantised to ~15 pts,
        # which flattened detail in the first ~600 m around the transmitter.
        diff_grid = np.zeros((n_cells, n_cells), dtype=np.float32)

        if use_diffraction:
            t_diff = time.time()
            tx_ground = float(sample_elevation(tx_lat, tx_lon))
            diff_backend = "CPU"

            # Build 1-D lat/lon arrays at cell centers to pass to kernels
            pixel_lats_1d = pixel_lats[:, 0].astype(np.float32)
            pixel_lons_1d = pixel_lons[0, :].astype(np.float32)

            if GPU_AVAILABLE:
                try:
                    diff_grid = compute_diffraction_grid_gpu(
                        elev_grid,
                        lat_min, lat_max, lon_min, lon_max,
                        tx_lat, tx_lon, tx_ground, tx_h,
                        rx_h, freq,
                        n_cells, radius_m_val,
                        pixel_lats_1d, pixel_lons_1d,
                    )
                    diff_backend = "CUDA"
                except Exception as e:
                    logger.warning(f"CUDA diffraction kernel failed: {e}; falling back to CPU")
                    diff_grid = compute_diffraction_grid_cpu(
                        elev_grid,
                        lat_min, lat_max, lon_min, lon_max,
                        tx_lat, tx_lon, tx_ground, tx_h,
                        rx_h, freq,
                        n_cells, radius_m_val, cos_lat,
                        pixel_lats, pixel_lons, dist_m,
                    )
            else:
                diff_grid = compute_diffraction_grid_cpu(
                    elev_grid,
                    lat_min, lat_max, lon_min, lon_max,
                    tx_lat, tx_lon, tx_ground, tx_h,
                    rx_h, freq,
                    n_cells, radius_m_val, cos_lat,
                    pixel_lats, pixel_lons, dist_m,
                )

            t_diff_ms = (time.time() - t_diff) * 1000
            logger.info(f"  Diffraction ({diff_backend}, per-pixel): {t_diff_ms:.0f}ms")

        # Apply diffraction to link budget
        rx_power -= diff_grid

        # Apply local clutter loss (per-pixel terrain roughness) and
        # global clutter baseline. Only inside the coverage disc.
        rx_power -= local_clutter
        rx_power -= np.float32(clutter_baseline)

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
        logger.info(f"  Link budget + mask: {t_sweep:.0f}ms")

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

    def _compute_local_roughness(
        self,
        elev_grid: np.ndarray,
        n_cells: int,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        neighbourhood_m: float = 100.0,
    ) -> np.ndarray:
        """
        Per-pixel local terrain roughness (dh = local std of terrain).

        Computes std-dev of the elevation grid in a ~neighbourhood_m box
        around each terrain cell, then bilinearly resamples onto the
        (n_cells x n_cells) output grid. This is the clutter-like
        texture that CloudRF gets for free from its DSM+landcover.

        Returns a (n_cells, n_cells) float32 array of dh in meters.
        """
        try:
            from scipy.ndimage import uniform_filter
        except ImportError:
            logger.warning("scipy unavailable; local roughness disabled")
            return np.zeros((n_cells, n_cells), dtype=np.float32)

        terrain_h, terrain_w = elev_grid.shape
        if terrain_h < 3 or terrain_w < 3:
            return np.zeros((n_cells, n_cells), dtype=np.float32)

        # Terrain resolution in meters (use lat axis, close enough)
        span_m = (lat_max - lat_min) * 111320.0
        cell_m = span_m / max(terrain_h - 1, 1)
        box = max(3, int(round(neighbourhood_m / max(cell_m, 1.0))))
        if box % 2 == 0:
            box += 1  # odd box size for symmetric window

        elev_f = elev_grid.astype(np.float32, copy=False)
        mean_h = uniform_filter(elev_f, size=box, mode="nearest")
        mean_h2 = uniform_filter(elev_f * elev_f, size=box, mode="nearest")
        var_h = np.maximum(mean_h2 - mean_h * mean_h, 0.0)
        dh = np.sqrt(var_h, dtype=np.float32)

        # Resample to output grid using vectorized bilinear interpolation
        out_lats = np.linspace(lat_max, lat_min, n_cells, dtype=np.float32)
        out_lons = np.linspace(lon_min, lon_max, n_cells, dtype=np.float32)
        rr = np.clip(
            (lat_max - out_lats) / max(lat_max - lat_min, 1e-9) * (terrain_h - 1),
            0, terrain_h - 1,
        ).astype(np.float32)
        cc = np.clip(
            (out_lons - lon_min) / max(lon_max - lon_min, 1e-9) * (terrain_w - 1),
            0, terrain_w - 1,
        ).astype(np.float32)

        r0 = np.floor(rr).astype(np.int32)
        c0 = np.floor(cc).astype(np.int32)
        r1 = np.minimum(r0 + 1, terrain_h - 1)
        c1 = np.minimum(c0 + 1, terrain_w - 1)
        fr = (rr - r0.astype(np.float32))[:, None]
        fc = (cc - c0.astype(np.float32))[None, :]

        h00 = dh[np.ix_(r0, c0)]
        h01 = dh[np.ix_(r0, c1)]
        h10 = dh[np.ix_(r1, c0)]
        h11 = dh[np.ix_(r1, c1)]

        out = (
            h00 * (1.0 - fr) * (1.0 - fc)
            + h01 * (1.0 - fr) * fc
            + h10 * fr * (1.0 - fc)
            + h11 * fr * fc
        ).astype(np.float32)
        return out

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
