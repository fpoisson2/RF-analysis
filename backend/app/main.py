"""
RF Planner API - Open source RF planning tool.

FastAPI backend with propagation models, terrain data, and coverage calculation.
"""
import os
import math
import time
import uuid
import logging

import numpy as np

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .schemas import AreaRequest, PathRequest, AreaResponse, PathResponse
from .coverage.engine import CoverageEngine, COLOR_SCHEMAS
from .terrain.srtm import SRTMManager
from .terrain.lidar_terrain import LiDARTerrainManager
from .propagation.models import MODELS, list_models
from .propagation.diffraction import DIFFRACTION_MODELS
from .gpu import gpu_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Data directories
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
SRTM_DIR = os.path.join(DATA_DIR, "srtm")
LIDAR_DIR = os.path.join(DATA_DIR, "lidar")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
os.makedirs(SRTM_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Initialize components
# SRTM as fallback, LiDAR as primary when available
srtm = SRTMManager(SRTM_DIR, auto_download=True)
terrain = LiDARTerrainManager(LIDAR_DIR, fallback_manager=srtm)
engine = CoverageEngine(terrain)

# FastAPI app
app = FastAPI(
    title="RF Planner",
    version="1.0.0",
    description="Open-source RF planning tool - alternative to CloudRF",
)

from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup_index():
    """Pre-index buildings at startup for fast MVT tile serving."""
    _ensure_buildings_indexed()


@app.get("/api/health")
def health():
    """Health check and system info."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "gpu": gpu_status(),
        "srtm_tiles": len(srtm.get_available_tiles()),
        "lidar": terrain.get_status() if hasattr(terrain, 'get_status') else None,
    }


@app.get("/api/models")
def get_models():
    """List available propagation models."""
    return {
        "propagation": list_models(),
        "diffraction": list(DIFFRACTION_MODELS.keys()),
        "color_schemas": {k: v["name"] for k, v in COLOR_SCHEMAS.items()},
    }


@app.post("/api/area")
def area_coverage(req: AreaRequest):
    """Calculate area coverage heatmap."""
    start = time.time()
    try:
        result = engine.calculate_area(req.model_dump())

        # Save heatmap image
        img_id = str(uuid.uuid4())[:8]
        img_path = os.path.join(OUTPUT_DIR, f"{img_id}.png")
        with open(img_path, "wb") as f:
            f.write(result["image_data"])

        # Store for raster tile serving (on disk for multi-worker support)
        import json as _json
        with open(_COVERAGE_IMG_PATH, "wb") as cf:
            cf.write(result["image_data"])
        with open(_COVERAGE_META_PATH, "w") as cf:
            _json.dump({"bounds": result["bounds"], "color_schema": req.output.get("units", "dBm") if hasattr(req.output, "get") else "dBm"}, cf)
        # Also save raw signal grid for smooth tile interpolation
        _COVERAGE_GRID_PATH = os.path.join(OUTPUT_DIR, "_coverage_grid.npy")
        np.save(_COVERAGE_GRID_PATH, engine._last_grid)

        elapsed = (time.time() - start) * 1000

        return AreaResponse(
            image_url=f"/api/tiles/{img_id}.png",
            bounds=result["bounds"],
            stats=result["stats"],
            erp_w=result["erp_w"],
            erp_dbm=result["erp_dbm"],
            eirp_w=result["eirp_w"],
            eirp_dbm=result["eirp_dbm"],
            computation_time_ms=elapsed,
        )
    except Exception as e:
        logger.exception("Area calculation failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/path")
def path_profile(req: PathRequest):
    """Calculate point-to-point path profile."""
    try:
        result = engine.calculate_path(req.model_dump())
        return PathResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Path calculation failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/coverage/sample")
def coverage_sample(data: dict):
    """Sample the latest coverage grid at given lat/lon points.
    Body: { "points": [[lat, lon], ...] }
    Returns: { "values": [dBm_or_null, ...] }
    Fast — no terrain queries, just grid lookup.
    """
    points = data.get("points", [])
    if not points:
        return {"values": []}

    grid = engine._last_grid
    bounds = engine._last_bounds if hasattr(engine, '_last_bounds') else None
    if grid is None or bounds is None:
        return {"values": [None] * len(points)}

    n = grid.shape[0]
    lat_min = bounds["south"]
    lat_max = bounds["north"]
    lon_min = bounds["west"]
    lon_max = bounds["east"]

    values = []
    for pt in points:
        lat_pt, lon_pt = pt[0], pt[1]
        r = int((lat_max - lat_pt) / (lat_max - lat_min) * n)
        c = int((lon_pt - lon_min) / (lon_max - lon_min) * n)
        if 0 <= r < n and 0 <= c < n and not np.isnan(grid[r, c]):
            values.append(round(float(grid[r, c]), 1))
        else:
            values.append(None)

    return {"values": values}


@app.post("/api/coverage/buildings3d")
def buildings_3d(data: dict):
    """
    Sample the latest coverage grid at building centroids and estimate
    rooftop vs street signal for 3D visualisation.

    Body: { "buildings": [ {"lat": ..., "lon": ..., "height": ...}, ... ] }
    Returns per-building signal_street, signal_roof, delta_db.
    """
    buildings = data.get("buildings", [])
    if not buildings:
        return {"results": []}
    results = engine.sample_buildings(buildings)
    return {"results": results}


@app.get("/api/tiles/{filename}")
def get_tile(filename: str):
    """Serve generated heatmap tiles."""
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, detail="Tile not found")
    return FileResponse(path, media_type="image/png")


# Store latest coverage for tile serving (on disk for multi-worker support)
_COVERAGE_META_PATH = os.path.join(OUTPUT_DIR, "_coverage_meta.json")
_COVERAGE_IMG_PATH = os.path.join(OUTPUT_DIR, "_coverage_latest.png")
_cov_tile_cache: dict = {"img": None, "bounds": None, "mtime": 0}


@app.get("/api/coverage/tiles/{z}/{x}/{y}.png")
def coverage_raster_tile(z: int, x: int, y: int):
    """Serve the latest coverage result as raster XYZ tiles.
    Solves MapLibre image source clipping with 3D terrain."""
    from PIL import Image as _Image
    import io as _io

    if not os.path.exists(_COVERAGE_IMG_PATH) or not os.path.exists(_COVERAGE_META_PATH):
        raise HTTPException(404, detail="No coverage computed yet")

    # Cache in memory per worker — reload only when file changes
    _COVERAGE_GRID_PATH = os.path.join(OUTPUT_DIR, "_coverage_grid.npy")
    mtime = os.path.getmtime(_COVERAGE_IMG_PATH)
    if _cov_tile_cache["mtime"] != mtime or _cov_tile_cache["img"] is None:
        import json as _json
        from PIL import Image as _PILImg
        _cov_tile_cache["img"] = np.array(_PILImg.open(_COVERAGE_IMG_PATH))
        with open(_COVERAGE_META_PATH) as mf:
            meta = _json.load(mf)
            _cov_tile_cache["bounds"] = meta.get("bounds", meta)
        if os.path.exists(_COVERAGE_GRID_PATH):
            _cov_tile_cache["grid"] = np.load(_COVERAGE_GRID_PATH)
        else:
            _cov_tile_cache["grid"] = None
        _cov_tile_cache["mtime"] = mtime

    src_img = _cov_tile_cache["img"]
    bounds = _cov_tile_cache["bounds"]
    raw_grid = _cov_tile_cache.get("grid")
    src_h, src_w = src_img.shape[:2]

    # Tile bounds (Web Mercator → WGS84)
    n = 2 ** z
    tile_lon_min = x / n * 360.0 - 180.0
    tile_lon_max = (x + 1) / n * 360.0 - 180.0
    tile_lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    tile_lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    cov_n = bounds["north"]
    cov_s = bounds["south"]
    cov_e = bounds["east"]
    cov_w = bounds["west"]

    TILE_PX = 512

    # Check overlap — return transparent tile if no overlap
    if tile_lon_max <= cov_w or tile_lon_min >= cov_e or tile_lat_max <= cov_s or tile_lat_min >= cov_n:
        img = _Image.new("RGBA", (TILE_PX, TILE_PX), (0, 0, 0, 0))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        from fastapi.responses import StreamingResponse
        return StreamingResponse(buf, media_type="image/png")

    # Map tile bounds to source image pixel coords
    x0 = int((tile_lon_min - cov_w) / (cov_e - cov_w) * src_w)
    x1 = int((tile_lon_max - cov_w) / (cov_e - cov_w) * src_w)
    y0 = int((cov_n - tile_lat_max) / (cov_n - cov_s) * src_h)
    y1 = int((cov_n - tile_lat_min) / (cov_n - cov_s) * src_h)

    # Clamp to source image
    x0_c = max(0, min(x0, src_w))
    x1_c = max(0, min(x1, src_w))
    y0_c = max(0, min(y0, src_h))
    y1_c = max(0, min(y1, src_h))

    if x1_c <= x0_c or y1_c <= y0_c or (x1 - x0) <= 0 or (y1 - y0) <= 0:
        img = _Image.new("RGBA", (TILE_PX, TILE_PX), (0, 0, 0, 0))
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        from fastapi.responses import StreamingResponse
        return StreamingResponse(buf, media_type="image/png")

    tile = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.uint8)
    total_w = x1 - x0
    total_h = y1 - y0

    dst_x0 = max(0, min(int((x0_c - x0) / total_w * TILE_PX), TILE_PX - 1))
    dst_x1 = max(dst_x0 + 1, min(int((x1_c - x0) / total_w * TILE_PX), TILE_PX))
    dst_y0 = max(0, min(int((y0_c - y0) / total_h * TILE_PX), TILE_PX - 1))
    dst_y1 = max(dst_y0 + 1, min(int((y1_c - y0) / total_h * TILE_PX), TILE_PX))

    dst_w = dst_x1 - dst_x0
    dst_h = dst_y1 - dst_y0

    if raw_grid is not None:
        # Interpolate raw signal values (bilinear) then colorize — smooth + correct colors
        grid_region = raw_grid[y0_c:y1_c, x0_c:x1_c].copy()
        if grid_region.size > 0:
            # Bilinear upscale of signal values
            pil_vals = _Image.fromarray(np.nan_to_num(grid_region, nan=-999).astype(np.float32), mode='F')
            pil_vals = pil_vals.resize((dst_w, dst_h), _Image.BILINEAR)
            upscaled = np.array(pil_vals)

            # Vectorized colorization using the same color stops as the engine
            from .coverage.engine import COLOR_SCHEMAS
            schema = COLOR_SCHEMAS.get("signal_strength", {})
            stops = schema.get("stops", [])
            valid = upscaled > -998
            region_tile = np.zeros((dst_h, dst_w, 4), dtype=np.uint8)
            # Apply colors from strongest to weakest (first match wins)
            for threshold, rgba in stops:
                mask = valid & (upscaled >= threshold)
                region_tile[mask] = rgba
                valid = valid & ~mask  # don't overwrite

            tile[dst_y0:dst_y0+dst_h, dst_x0:dst_x0+dst_w] = region_tile
    else:
        # Fallback: use pre-rendered image with NEAREST
        region = src_img[y0_c:y1_c, x0_c:x1_c]
        if region.size > 0:
            pil_region = _Image.fromarray(region)
            pil_region = pil_region.resize((dst_w, dst_h), _Image.NEAREST)
            tile[dst_y0:dst_y1, dst_x0:dst_x1] = np.array(pil_region)

    img = _Image.fromarray(tile, "RGBA")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(buf, media_type="image/png",
                             headers={"Cache-Control": "public, max-age=300"})


@app.get("/api/terrain/render")
def render_terrain(lat: float, lon: float, radius_km: float = 2.0,
                    resolution_m: float = 5, mode: str = "elevation"):
    """
    Render terrain data as a PNG image for map overlay.
    Uses native LiDAR resolution via block read (fast, precise).
    mode: 'elevation' (DTM), 'canopy' (MHC heights), 'surface' (DTM+MHC)
    """
    import io as _io
    from PIL import Image as _Image

    cos_lat = math.cos(math.radians(lat))
    half_lat = radius_km / 111.32
    half_lon = radius_km / (111.32 * cos_lat)

    lat_min = lat - half_lat
    lat_max = lat + half_lat
    lon_min = lon - half_lon
    lon_max = lon + half_lon

    # Try native LiDAR block read (much faster and more precise)
    ds_type = "mhc" if mode == "canopy" else "mnt"
    block = None
    if hasattr(terrain, 'read_block'):
        block = terrain.read_block(lat_min, lon_min, lat_max, lon_max,
                                    dataset_type=ds_type, max_pixels=1500)

    # Always use the requested bounds so the overlay matches the map area
    req_bounds = {"north": lat_max, "south": lat_min, "east": lon_max, "west": lon_min}

    if block is not None:
        grid, meta = block
        n_h, n_w = grid.shape

        # For surface mode: add MNT to MHC
        if mode == "surface":
            mnt_block = terrain.read_block(lat_min, lon_min, lat_max, lon_max,
                                            dataset_type="mnt", max_pixels=1500)
            if mnt_block is not None:
                mnt_data, _ = mnt_block
                if mnt_data.shape != grid.shape:
                    from PIL import Image as _Img
                    mnt_img = _Img.fromarray(mnt_data)
                    mnt_img = mnt_img.resize((n_w, n_h), _Img.BILINEAR)
                    mnt_data = np.array(mnt_img)
                grid = mnt_data + np.maximum(grid, 0)

        # read_block already returns WGS84-aligned grid with correct bounds
        bounds = req_bounds
    else:
        # Fallback: point-by-point (slow)
        n = int(2 * radius_km * 1000 / resolution_m)
        n = max(10, min(n, 500))
        lats = np.linspace(lat_max, lat_min, n)
        lons = np.linspace(lon_min, lon_max, n)
        grid = np.zeros((n, n), dtype=np.float32)
        for r in range(n):
            for c in range(n):
                try:
                    if mode == "canopy":
                        s = terrain.get_elevation(lats[r], lons[c], use_canopy=True)
                        g = terrain.get_elevation(lats[r], lons[c], use_canopy=False)
                        grid[r, c] = max(0, s - g)
                    else:
                        grid[r, c] = terrain.get_elevation(lats[r], lons[c],
                                        use_canopy=(mode == "surface"))
                except Exception:
                    grid[r, c] = 0
        n_h, n_w = n, n
        bounds = req_bounds

    # Clean NaN
    grid = np.nan_to_num(grid, nan=0.0)
    valid = grid[grid > -100]
    if len(valid) == 0:
        return {"error": "No terrain data in this area"}
    vmin = float(np.min(valid[valid > 0])) if np.any(valid > 0) else 0
    vmax = float(np.max(valid))

    # Render to RGBA image
    image = np.zeros((n_h, n_w, 4), dtype=np.uint8)

    if mode == "canopy":
        # Height-class coloring with vectorized operations
        m1 = (grid >= 0.5) & (grid < 3)
        m2 = (grid >= 3) & (grid < 8)
        m3 = (grid >= 8) & (grid < 15)
        m4 = (grid >= 15) & (grid < 25)
        m5 = (grid >= 25) & (grid < 50)
        m6 = grid >= 50

        image[m1] = [120, 200, 80, 180]    # Low veg
        image[m2] = [40, 160, 40, 200]     # Trees
        image[m3] = [20, 120, 20, 210]     # Tall trees
        image[m4] = [180, 120, 60, 220]    # Small buildings
        image[m5] = [200, 80, 40, 230]     # Medium buildings
        image[m6] = [220, 40, 40, 240]     # Tall buildings
    elif mode == "surface":
        t = np.clip((grid - vmin) / max(vmax - vmin, 1), 0, 1)
        image[:, :, 0] = np.clip(80 + t * 160, 0, 255).astype(np.uint8)
        image[:, :, 1] = np.clip(160 - t * 80, 0, 255).astype(np.uint8)
        image[:, :, 2] = np.clip(60 - t * 30, 0, 255).astype(np.uint8)
        image[:, :, 3] = 200
    else:
        t = np.clip((grid - vmin) / max(vmax - vmin, 1), 0, 1)
        image[:, :, 0] = np.clip(t * 255, 0, 255).astype(np.uint8)
        image[:, :, 1] = np.clip(200 - t * 120, 0, 255).astype(np.uint8)
        image[:, :, 2] = np.clip(80 - t * 40 + (t > 0.8) * t * 200, 0, 255).astype(np.uint8)
        image[:, :, 3] = 190

    img = _Image.fromarray(image, "RGBA")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")

    img_id = str(uuid.uuid4())[:8]
    img_path = os.path.join(OUTPUT_DIR, f"terrain_{img_id}.png")
    with open(img_path, "wb") as f:
        f.write(buf.getvalue())

    return {
        "image_url": f"/api/tiles/terrain_{img_id}.png",
        "bounds": bounds,
        "stats": {
            "min": round(vmin, 1),
            "max": round(vmax, 1),
            "resolution_m": block[1].get("resolution_m", resolution_m) if block else resolution_m,
            "native_resolution_m": block[1].get("native_resolution_m") if block else None,
            "grid_size": f"{n_w}x{n_h}",
            "mode": mode,
            "source": "LiDAR" if block else "SRTM",
        },
    }


def _srtm_block_read(srtm_mgr, lat_min, lon_min, lat_max, lon_max, out_size):
    """Fast SRTM block read with bilinear interpolation on the raw grid.
    Guarantees consistent values at tile edges because sampling is deterministic
    for a given lat/lon regardless of which DEM tile requests it."""

    # Generate exact lat/lon for each output pixel
    lats = np.linspace(lat_max, lat_min, out_size)  # top to bottom
    lons = np.linspace(lon_min, lon_max, out_size)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    output = np.zeros((out_size, out_size), dtype=np.float32)

    # Group pixels by SRTM tile
    tile_lat = np.floor(lat_grid).astype(int)
    tile_lon = np.floor(lon_grid).astype(int)

    # Find unique tiles needed
    unique_tiles = set(zip(tile_lat.ravel(), tile_lon.ravel()))

    for (tlat, tlon) in unique_tiles:
        t = srtm_mgr._get_tile(tlat, tlon)
        if t is None:
            continue
        data, sz = t

        # Mask of pixels belonging to this tile
        mask = (tile_lat == tlat) & (tile_lon == tlon)
        if not np.any(mask):
            continue

        # Fractional position within tile
        lat_frac = lat_grid[mask] - tlat
        lon_frac = lon_grid[mask] - tlon

        # Pixel coordinates (SRTM: row 0 = north edge of tile = lat+1)
        row = (1.0 - lat_frac) * (sz - 1)
        col = lon_frac * (sz - 1)

        r0 = np.clip(np.floor(row).astype(int), 0, sz - 1)
        c0 = np.clip(np.floor(col).astype(int), 0, sz - 1)
        r1 = np.clip(r0 + 1, 0, sz - 1)
        c1 = np.clip(c0 + 1, 0, sz - 1)

        dr = row - r0
        dc = col - c0

        # Bilinear interpolation
        z00 = data[r0, c0].astype(np.float32)
        z01 = data[r0, c1].astype(np.float32)
        z10 = data[r1, c0].astype(np.float32)
        z11 = data[r1, c1].astype(np.float32)

        # Handle voids
        void_mask = (z00 <= -32768) | (z01 <= -32768) | (z10 <= -32768) | (z11 <= -32768)

        z = (z00 * (1 - dr) * (1 - dc) +
             z01 * (1 - dr) * dc +
             z10 * dr * (1 - dc) +
             z11 * dr * dc)

        z[void_mask] = 0.0
        z = np.maximum(z, 0.0)

        output[mask] = z

    return output


DEM_CACHE_DIR = os.path.join(OUTPUT_DIR, "dem_cache")
os.makedirs(DEM_CACHE_DIR, exist_ok=True)

@app.get("/api/terrain/dem/{z}/{x}/{y}.png")
def terrain_dem_tile(z: int, x: int, y: int, mode: str = "terrain"):
    """
    Serve raster-dem tiles in Mapbox Terrain-RGB encoding for MapLibre setTerrain().
    Uses LiDAR (MNS/MNT) with SRTM fallback. Cached to disk.
    Encoding: elevation = -10000 + (R*256*256 + G*256 + B) * 0.1
    """
    import io as _io
    from PIL import Image as _Image

    # Check disk cache first (validate file is a real PNG > 1KB)
    cache_path = os.path.join(DEM_CACHE_DIR, f"{z}_{x}_{y}_{mode}.png")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
        return FileResponse(cache_path, media_type="image/png",
                           headers={"Cache-Control": "public, max-age=86400"})

    tile_size = 256

    try:
        return _generate_dem_tile(z, x, y, mode, tile_size, cache_path)
    except Exception as e:
        logger.warning(f"DEM tile {z}/{x}/{y} failed: {e}")
        # Return 404 — MapLibre will upsample from parent tile instead of showing a hole
        raise HTTPException(status_code=404, detail="DEM tile generation failed")


def _generate_dem_tile(z, x, y, mode, tile_size, cache_path):
    import io as _io
    from PIL import Image as _Image

    # Tile bounds (Web Mercator → WGS84)
    n = 2 ** z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    use_canopy = mode == "surface"

    # Always get SRTM as base layer (padded for seamless edges)
    grid = _srtm_block_read(srtm, lat_min, lon_min, lat_max, lon_max, tile_size)

    # Overlay LiDAR where available
    if hasattr(terrain, 'read_block'):
        block = terrain.read_block(lat_min, lon_min, lat_max, lon_max,
                                    dataset_type="mnt", max_pixels=tile_size)
        if block is not None:
            lidar_grid = block[0]
            if use_canopy:
                canopy_block = terrain.read_block(lat_min, lon_min, lat_max, lon_max,
                                                   dataset_type="mhc", max_pixels=tile_size)
                if canopy_block is not None:
                    cb = canopy_block[0]
                    if cb.shape != lidar_grid.shape:
                        cb_img = _Image.fromarray(cb)
                        cb_img = cb_img.resize((lidar_grid.shape[1], lidar_grid.shape[0]), _Image.BILINEAR)
                        cb = np.array(cb_img)
                    lidar_grid = lidar_grid + np.maximum(cb, 0)

            if lidar_grid.shape != grid.shape:
                lidar_img = _Image.fromarray(lidar_grid)
                lidar_img = lidar_img.resize((grid.shape[1], grid.shape[0]), _Image.BILINEAR)
                lidar_grid = np.array(lidar_img, dtype=np.float32)

            valid = ~np.isnan(lidar_grid) & (lidar_grid > -100)
            grid[valid] = lidar_grid[valid]

    # Resize padded grid to tile_size, then crop to tile_size
    if grid.shape[0] != tile_size or grid.shape[1] != tile_size:
        img_tmp = _Image.fromarray(grid)
        img_tmp = img_tmp.resize((tile_size, tile_size), _Image.BILINEAR)
        grid = np.array(img_tmp, dtype=np.float32)

    # Encode as Mapbox Terrain-RGB: val = (elev + 10000) * 10
    grid = np.nan_to_num(grid, nan=0.0)
    val = ((grid + 10000.0) * 10.0).astype(np.int32)
    val = np.clip(val, 0, 256 * 256 * 256 - 1)

    r_ch = (val >> 16) & 0xFF
    g_ch = (val >> 8) & 0xFF
    b_ch = val & 0xFF

    image = np.stack([r_ch, g_ch, b_ch], axis=-1).astype(np.uint8)

    img = _Image.fromarray(image, "RGB")
    img.save(cache_path, format="PNG")

    return FileResponse(cache_path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/elevation")
def get_elevation(lat: float, lon: float):
    """Get terrain elevation at a point."""
    elev = srtm.get_elevation(lat, lon)
    return {"lat": lat, "lon": lon, "elevation_m": round(elev, 1)}


@app.get("/api/profile")
def get_profile(lat1: float, lon1: float, lat2: float, lon2: float, points: int = 200):
    """Get terrain elevation profile between two points."""
    distances, elevations = srtm.get_profile(lat1, lon1, lat2, lon2, points)
    return {
        "distances_m": [round(d, 1) for d in distances.tolist()],
        "elevations_m": [round(e, 1) for e in elevations.tolist()],
    }


@app.get("/api/data/status")
def data_status():
    """Get status of available data (SRTM tiles, etc.)."""
    tiles = srtm.get_available_tiles()

    # Check buildings
    buildings_dir = os.path.join(DATA_DIR, "buildings")
    buildings_files = []
    if os.path.exists(buildings_dir):
        buildings_files = [f for f in os.listdir(buildings_dir) if f.endswith('.geojson')]

    # Check LiDAR
    lidar_dir = os.path.join(DATA_DIR, "lidar")
    lidar_files = []
    if os.path.exists(lidar_dir):
        for root, dirs, files in os.walk(lidar_dir):
            for f in files:
                if f.endswith(('.tif', '.tiff', '.las', '.laz')):
                    lidar_files.append(f)

    return {
        "srtm": {"tiles_available": len(tiles), "tiles": tiles[:50]},
        "buildings": {"files": buildings_files, "count": len(buildings_files)},
        "lidar": {"files": lidar_files[:50], "count": len(lidar_files)},
    }


@app.post("/api/data/download/quebec-city")
def download_quebec_city_data():
    """Download buildings + LiDAR data for Quebec City."""
    from .download_quebec import download_all_quebec_city
    try:
        result = download_all_quebec_city(DATA_DIR)
        return result
    except Exception as e:
        logger.exception("Download failed")
        raise HTTPException(status_code=500, detail=str(e))


def _fetch_osm_buildings(lat, lon, radius_km):
    """Fetch building footprints from OpenStreetMap Overpass API."""
    import urllib.request, urllib.parse, json as _json
    half_lat = radius_km / 111.32
    cos_lat = math.cos(math.radians(lat))
    half_lon = radius_km / (111.32 * cos_lat)
    bbox = f"{lat-half_lat},{lon-half_lon},{lat+half_lat},{lon+half_lon}"
    query = f'[out:json][timeout:30];(way["building"]({bbox});relation["building"]({bbox}););(._;>;);out body;'
    url = 'https://overpass-api.de/api/interpreter'
    try:
        req = urllib.request.Request(url, data=f'data={urllib.parse.quote(query)}'.encode(),
                                     headers={"User-Agent": "RF-Planner/1.0"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = _json.loads(resp.read())
    except Exception as e:
        logger.warning(f"OSM Overpass failed: {e}")
        return []

    # Build node index
    nodes = {}
    for el in data.get("elements", []):
        if el["type"] == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])

    # Also build way geometry index for relations
    ways = {}
    for el in data.get("elements", []):
        if el["type"] == "way":
            nds = el.get("nodes", [])
            coords = [nodes[n] for n in nds if n in nodes]
            if coords:
                ways[el["id"]] = coords

    def _extract_height(tags):
        height = None
        if "height" in tags:
            try: height = float(tags["height"].replace("m", "").strip())
            except: pass
        if height is None and "building:levels" in tags:
            try: height = float(tags["building:levels"]) * 3.5
            except: pass
        return height

    def _make_feature(el_id, tags, rings):
        if not rings:
            return None
        # Use outer ring(s)
        if len(rings) == 1:
            geom = {"type": "Polygon", "coordinates": [rings[0]]}
        else:
            geom = {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
        return {
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "ID": f"osm_{el_id}",
                "SOURCE_CAPTAGE": "OpenStreetMap",
                "TYPE_BATIMENT": tags.get("building", "yes"),
                "_height": _extract_height(tags),
                "name": tags.get("name"),
            },
        }

    features = []
    for el in data.get("elements", []):
        if el["type"] == "way":
            tags = el.get("tags", {})
            if "building" not in tags:
                continue
            nds = el.get("nodes", [])
            coords = [nodes[n] for n in nds if n in nodes]
            if len(coords) < 4:
                continue
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            feat = _make_feature(el["id"], tags, [coords])
            if feat:
                features.append(feat)

        elif el["type"] == "relation":
            tags = el.get("tags", {})
            if "building" not in tags:
                continue
            # Collect outer rings from relation members
            outer_rings = []
            for member in el.get("members", []):
                if member.get("type") == "way" and member.get("role", "outer") == "outer":
                    wid = member["ref"]
                    if wid in ways:
                        ring = ways[wid]
                        if len(ring) >= 4:
                            if ring[0] != ring[-1]:
                                ring.append(ring[0])
                            outer_rings.append(ring)
            feat = _make_feature(el["id"], tags, outer_rings)
            if feat:
                features.append(feat)

    return features


# Cache for OSM buildings (key: rounded lat/lon/radius)
_osm_cache: dict = {}

# Cache for local buildings file (loaded once into memory)
_local_buildings_cache: dict = {"data": None}

BUILDINGS_CACHE_DIR = os.path.join(OUTPUT_DIR, "buildings_cache")
BUILDINGS_MVT_CACHE = os.path.join(OUTPUT_DIR, "buildings_mvt")
os.makedirs(BUILDINGS_MVT_CACHE, exist_ok=True)

# Pre-indexed buildings for vector tile serving
_buildings_spatial_index: dict = {"features": None, "grid": None, "loaded": False}
_GRID_RES = 0.01  # ~1km grid cells for spatial index


def _ensure_buildings_indexed():
    """Load and spatially index all buildings for fast MVT tile generation.
    Uses cached buildings (with LiDAR heights + OSM) if available."""
    if _buildings_spatial_index["loaded"]:
        return _buildings_spatial_index["features"]

    import json as _json, glob

    features = []

    # Try loading from buildings cache first (has LiDAR heights + OSM data)
    cache_files = sorted(glob.glob(os.path.join(BUILDINGS_CACHE_DIR, "buildings_*.json")),
                         key=os.path.getsize, reverse=True)
    source_data = None
    if cache_files:
        logger.info(f"Loading MVT buildings from cache: {cache_files[0]}")
        with open(cache_files[0]) as f:
            source_data = _json.load(f)
    else:
        # Fallback: load raw local file
        buildings_path = os.path.join(DATA_DIR, "buildings", "quebec_city_batiments.geojson")
        if os.path.exists(buildings_path):
            logger.info("Loading MVT buildings from raw GeoJSON (no cache yet)...")
            with open(buildings_path) as f:
                source_data = _json.load(f)

    if source_data:
        for feat in source_data.get("features", []):
            geom = feat.get("geometry")
            if not geom:
                continue
            coords = geom.get("coordinates", [])
            try:
                if geom["type"] == "Polygon":
                    ring = coords[0]
                elif geom["type"] == "MultiPolygon":
                    ring = coords[0][0]
                else:
                    continue
                clat = sum(p[1] for p in ring) / len(ring)
                clon = sum(p[0] for p in ring) / len(ring)

                props = feat.get("properties", {})
                height = props.get("_height") or props.get("height") or 8.0
                try:
                    height = float(height)
                except (ValueError, TypeError):
                    height = 8.0

                features.append({
                    "geometry": geom,
                    "properties": {"h": height, "t": props.get("TYPE_BATIMENT", "")},
                    "clat": clat,
                    "clon": clon,
                })
            except (IndexError, KeyError, TypeError):
                continue

        logger.info(f"Indexed {len(features)} buildings for MVT")

    # Build spatial grid index for fast tile lookups
    from collections import defaultdict
    grid = defaultdict(list)
    for i, feat in enumerate(features):
        gkey = (int(feat["clat"] / _GRID_RES), int(feat["clon"] / _GRID_RES))
        grid[gkey].append(i)
    logger.info(f"Spatial grid: {len(grid)} cells")

    _buildings_spatial_index["features"] = features
    _buildings_spatial_index["grid"] = dict(grid)
    _buildings_spatial_index["loaded"] = True
    return features


@app.get("/api/buildings/tiles/{z}/{x}/{y}.pbf")
def buildings_vector_tile(z: int, x: int, y: int):
    """Serve buildings as Mapbox Vector Tiles for efficient GPU rendering."""
    import mapbox_vector_tile as mvt
    from fastapi.responses import Response

    # Check cache
    cache_path = os.path.join(BUILDINGS_MVT_CACHE, f"{z}_{x}_{y}.pbf")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        return Response(
            content=open(cache_path, "rb").read(),
            media_type="application/x-protobuf",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Tile bounds
    n = 2 ** z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    # Small buffer for edge features
    buf_lat = (lat_max - lat_min) * 0.05
    buf_lon = (lon_max - lon_min) * 0.05

    all_features = _ensure_buildings_indexed()
    grid = _buildings_spatial_index.get("grid", {})
    if not all_features:
        return Response(content=b"", media_type="application/x-protobuf")

    # Use spatial grid for fast lookup
    lat_min_g = int((lat_min - buf_lat) / _GRID_RES)
    lat_max_g = int((lat_max + buf_lat) / _GRID_RES) + 1
    lon_min_g = int((lon_min - buf_lon) / _GRID_RES)
    lon_max_g = int((lon_max + buf_lon) / _GRID_RES) + 1

    candidate_indices = set()
    for glat in range(lat_min_g, lat_max_g + 1):
        for glon in range(lon_min_g, lon_max_g + 1):
            candidate_indices.update(grid.get((glat, glon), []))

    tile_features = []
    for idx in candidate_indices:
        feat = all_features[idx]
        if (lat_min - buf_lat <= feat["clat"] <= lat_max + buf_lat and
            lon_min - buf_lon <= feat["clon"] <= lon_max + buf_lon):
            tile_features.append({
                "geometry": feat["geometry"],
                "properties": feat["properties"],
            })

    if not tile_features:
        # Empty tile
        content = mvt.encode([{"name": "buildings", "features": []}],
                             quantize_bounds=(lon_min, lat_min, lon_max, lat_max))
    else:
        mvt_features = []
        for f in tile_features:
            mvt_features.append({
                "geometry": f["geometry"],
                "properties": f["properties"],
            })

        content = mvt.encode(
            [{"name": "buildings", "features": mvt_features}],
            quantize_bounds=(lon_min, lat_min, lon_max, lat_max),
        )

    # Cache
    with open(cache_path, "wb") as fout:
        fout.write(content)

    return Response(
        content=content,
        media_type="application/x-protobuf",
        headers={"Cache-Control": "public, max-age=86400"},
    )
os.makedirs(BUILDINGS_CACHE_DIR, exist_ok=True)


def _load_local_buildings():
    """Load local buildings file once into memory."""
    if _local_buildings_cache["data"] is not None:
        return _local_buildings_cache["data"]
    import json
    buildings_path = os.path.join(DATA_DIR, "buildings", "quebec_city_batiments.geojson")
    if os.path.exists(buildings_path):
        logger.info("Loading local buildings file into memory...")
        with open(buildings_path) as f:
            _local_buildings_cache["data"] = json.load(f)
        logger.info(f"Loaded {len(_local_buildings_cache['data'].get('features', []))} buildings")
    else:
        _local_buildings_cache["data"] = {"features": []}
    return _local_buildings_cache["data"]


@app.get("/api/data/buildings_binary")
def get_buildings_binary(lat: float, lon: float, radius_km: float = 2.0):
    """Serve buildings in a compact binary format for deck.gl.
    Returns: JSON with flat arrays instead of GeoJSON features.
    Much smaller and faster to parse than full GeoJSON."""
    import json as _json

    # Use disk cache
    cache_key_str = f"{round(lat,2)}_{round(lon,2)}_{round(radius_km,1)}"
    bin_cache = os.path.join(BUILDINGS_CACHE_DIR, f"buildings_bin_{cache_key_str}.json")
    if os.path.exists(bin_cache):
        return FileResponse(bin_cache, media_type="application/json",
                           headers={"Cache-Control": "public, max-age=86400"})

    # Get full buildings (from existing cache or compute)
    full_cache = os.path.join(BUILDINGS_CACHE_DIR, f"buildings_{cache_key_str}.json")
    if os.path.exists(full_cache):
        with open(full_cache) as f:
            data = _json.load(f)
    else:
        data = get_buildings(lat, lon, radius_km)

    # Convert to flat arrays: polygons as [positions[], heights[], polygon_indices[]]
    positions = []    # flat [lon, lat, lon, lat, ...]
    heights = []      # one per polygon
    poly_starts = [0] # start index in positions for each polygon
    n_verts_total = 0

    for feat in data.get("features", []):
        geom = feat.get("geometry")
        if not geom:
            continue
        h = feat.get("properties", {}).get("_height", 8.0)
        try:
            h = float(h)
        except:
            h = 8.0

        if geom["type"] == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom["type"] == "MultiPolygon":
            rings = [poly[0] for poly in geom["coordinates"]]
        else:
            continue

        for ring in rings:
            for pt in ring:
                positions.append(round(pt[0], 5))
                positions.append(round(pt[1], 5))
                n_verts_total += 1
            heights.append(h)
            poly_starts.append(n_verts_total)

    result = {
        "positions": positions,
        "heights": heights,
        "polyStarts": poly_starts,
        "count": len(heights),
    }

    with open(bin_cache, 'w') as f:
        _json.dump(result, f)

    return FileResponse(bin_cache, media_type="application/json",
                       headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/data/buildings")
def get_buildings(lat: float, lon: float, radius_km: float = 2.0):
    """Get building footprints near a point (local data + OSM). Cached to disk."""
    import json

    # Check disk cache first (key: rounded position + radius)
    cache_key_str = f"{round(lat,2)}_{round(lon,2)}_{round(radius_km,1)}"
    cache_path = os.path.join(BUILDINGS_CACHE_DIR, f"buildings_{cache_key_str}.json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    local_data = _load_local_buildings()

    # Fetch OSM buildings in grid cells (10km each to avoid Overpass timeout)
    osm_features = []
    osm_cell_size = 0.09  # ~10km in degrees
    cos_lat_v = math.cos(math.radians(lat))
    lat_lo = lat - radius_km / 111.32
    lat_hi = lat + radius_km / 111.32
    lon_lo = lon - radius_km / (111.32 * cos_lat_v)
    lon_hi = lon + radius_km / (111.32 * cos_lat_v)

    import numpy as _np
    grid_lats = _np.arange(lat_lo, lat_hi, osm_cell_size)
    grid_lons = _np.arange(lon_lo, lon_hi, osm_cell_size)

    for glat in grid_lats:
        for glon in grid_lons:
            cell_key = (round(glat / osm_cell_size), round(glon / osm_cell_size))
            if cell_key not in _osm_cache:
                cell_lat = glat + osm_cell_size / 2
                cell_lon = glon + osm_cell_size / 2
                _osm_cache[cell_key] = _fetch_osm_buildings(cell_lat, cell_lon, osm_cell_size * 111.32 / 2)
            osm_features.extend(_osm_cache.get(cell_key, []))

    # Deduplicate: remove local buildings whose centroid is inside any OSM bounding box
    # Build list of OSM bounding boxes
    osm_bboxes = []
    for f in osm_features:
        g = f.get("geometry")
        if not g:
            continue
        try:
            all_pts = []
            if g["type"] == "Polygon":
                all_pts = g["coordinates"][0]
            elif g["type"] == "MultiPolygon":
                for poly in g["coordinates"]:
                    all_pts.extend(poly[0])
            if all_pts:
                lats_r = [p[1] for p in all_pts]
                lons_r = [p[0] for p in all_pts]
                osm_bboxes.append((min(lats_r), max(lats_r), min(lons_r), max(lons_r)))
        except (IndexError, KeyError):
            pass

    # Also collect OSM centroids for proximity-based dedup
    osm_centroids = []
    for f in osm_features:
        g = f.get("geometry")
        if not g:
            continue
        try:
            all_pts = []
            if g["type"] == "Polygon":
                all_pts = g["coordinates"][0]
            elif g["type"] == "MultiPolygon":
                for poly in g["coordinates"]:
                    all_pts.extend(poly[0])
            if all_pts:
                osm_centroids.append((
                    sum(p[1] for p in all_pts) / len(all_pts),
                    sum(p[0] for p in all_pts) / len(all_pts),
                ))
        except (IndexError, KeyError):
            pass

    def _in_any_osm_bbox(clat, clon):
        # Check bounding box overlap
        for lat_lo, lat_hi, lon_lo, lon_hi in osm_bboxes:
            if lat_lo <= clat <= lat_hi and lon_lo <= clon <= lon_hi:
                return True
        # Check proximity to OSM centroid (~20m threshold)
        threshold = 0.0002  # ~22m
        for olat, olon in osm_centroids:
            if abs(clat - olat) < threshold and abs(clon - olon) < threshold:
                return True
        return False

    deduped_local = []
    for f in local_data.get("features", []):
        g = f.get("geometry")
        if not g:
            continue
        coords = g.get("coordinates", [])
        try:
            if g["type"] == "Polygon":
                ring = coords[0]
            elif g["type"] == "MultiPolygon":
                ring = coords[0][0]
            else:
                deduped_local.append(f)
                continue
            clat = sum(p[1] for p in ring) / len(ring)
            clon = sum(p[0] for p in ring) / len(ring)
            if not _in_any_osm_bbox(clat, clon):
                deduped_local.append(f)
        except (IndexError, KeyError):
            deduped_local.append(f)

    # OSM first (better heights/names), then local to fill gaps
    data = {"features": osm_features + deduped_local}

    # Filter buildings within radius
    import math
    cos_lat = math.cos(math.radians(lat))
    lat_range = radius_km / 111.32
    lon_range = radius_km / (111.32 * cos_lat)

    # Pass 1: filter by bounding box, collect centroids
    candidates = []
    for feature in data.get("features", []):
        geom = feature.get("geometry")
        if geom is None:
            continue
        coords = geom.get("coordinates", [])
        try:
            if geom["type"] == "Polygon":
                ring = coords[0]
            elif geom["type"] == "MultiPolygon":
                ring = coords[0][0]
            else:
                continue
            clat = sum(p[1] for p in ring) / len(ring)
            clon = sum(p[0] for p in ring) / len(ring)
            if abs(clat - lat) <= lat_range and abs(clon - lon) <= lon_range:
                candidates.append((feature, clat, clon))
        except (IndexError, KeyError, TypeError):
            continue

    # Pass 2: batch LiDAR height lookup via block read (only within 5km for perf)
    mhc_grid = None
    mhc_meta = None
    lidar_radius = min(radius_km, 5.0)
    lidar_lat_range = lidar_radius / 111.32
    lidar_lon_range = lidar_radius / (111.32 * cos_lat)
    if candidates and hasattr(terrain, 'read_block'):
        blk_lat_min = lat - lidar_lat_range
        blk_lat_max = lat + lidar_lat_range
        blk_lon_min = lon - lidar_lon_range
        blk_lon_max = lon + lidar_lon_range
        pad = 0.001
        try:
            block = terrain.read_block(blk_lat_min - pad, blk_lon_min - pad,
                                        blk_lat_max + pad, blk_lon_max + pad,
                                        dataset_type="mhc", max_pixels=2000)
            if block is not None:
                mhc_grid, mhc_meta = block
        except Exception:
            pass

    def _to_rc(lat_pt, lon_pt):
        """Convert lat/lon to row/col in the MHC grid."""
        if mhc_grid is None or mhc_meta is None:
            return None, None
        lat_min_b = mhc_meta.get("lat_min", mhc_meta.get("south", 0))
        lat_max_b = mhc_meta.get("lat_max", mhc_meta.get("north", 0))
        lon_min_b = mhc_meta.get("lon_min", mhc_meta.get("west", 0))
        lon_max_b = mhc_meta.get("lon_max", mhc_meta.get("east", 0))
        if lat_max_b <= lat_min_b or lon_max_b <= lon_min_b:
            return None, None
        r = int((lat_max_b - lat_pt) / (lat_max_b - lat_min_b) * mhc_grid.shape[0])
        c = int((lon_pt - lon_min_b) / (lon_max_b - lon_min_b) * mhc_grid.shape[1])
        r = max(0, min(r, mhc_grid.shape[0] - 1))
        c = max(0, min(c, mhc_grid.shape[1] - 1))
        return r, c

    def _sample_mhc_polygon(ring):
        """Sample canopy height across a building polygon footprint.
        Uses 90th percentile instead of max to avoid picking up
        adjacent tall structures that bleed into the bounding box."""
        if mhc_grid is None:
            return None
        # Get bounding box of polygon in grid coords
        rows, cols = [], []
        for pt in ring:
            r, c = _to_rc(pt[1], pt[0])
            if r is not None:
                rows.append(r)
                cols.append(c)
        if not rows:
            return None
        r_min, r_max = max(0, min(rows)), min(mhc_grid.shape[0] - 1, max(rows))
        c_min, c_max = max(0, min(cols)), min(mhc_grid.shape[1] - 1, max(cols))
        block = mhc_grid[r_min:r_max + 1, c_min:c_max + 1]
        if block.size == 0:
            return None
        valid = block[block > 2.0]
        if len(valid) == 0:
            return None
        # Use median — resistant to tall neighbor bleed in the bounding box
        val = float(np.median(valid))
        return val if val > 2.0 else None

    # Pass 3: assign heights
    filtered = []
    for feature, clat, clon in candidates:
        props = feature.get("properties", {})
        height = None

        # Try explicit height properties
        for hk in ["ELEVATION", "HAUTEUR", "hauteur", "HEIGHT", "NB_ETAGES"]:
            if hk in props and props[hk]:
                try:
                    val = float(props[hk])
                    height = val if hk != "NB_ETAGES" else val * 3.0
                    break
                except (ValueError, TypeError):
                    pass

        # Try LiDAR canopy height — sample max across polygon footprint
        if height is None:
            geom = feature["geometry"]
            coords = geom["coordinates"]
            ring = coords[0] if geom["type"] == "Polygon" else coords[0][0]
            lidar_h = _sample_mhc_polygon(ring)
            if lidar_h is not None:
                height = round(lidar_h, 1)

        # Fallback by building type
        if height is None:
            btype = (props.get("TYPE_BATIMENT") or "").lower()
            if "commercial" in btype or "industriel" in btype:
                height = 12.0
            elif "institutionnel" in btype or "public" in btype:
                height = 15.0
            else:
                height = 8.0

        filtered.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": {**props, "_height": height},
        })

    result = {
        "type": "FeatureCollection",
        "features": filtered,
        "total_in_area": len(filtered),
    }

    # Save to disk cache for instant loading next time
    try:
        import json as _json
        with open(cache_path, 'w') as f:
            _json.dump(result, f)
        logger.info(f"Buildings cached: {cache_path} ({len(filtered)} features)")
    except Exception as e:
        logger.warning(f"Failed to cache buildings: {e}")

    return result
