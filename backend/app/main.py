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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    """Fast SRTM block read: slice HGT arrays directly instead of point-by-point."""
    from PIL import Image as _Img

    # Collect unique tiles needed
    lat_tiles = range(math.floor(lat_min), math.floor(lat_max) + 1)
    lon_tiles = range(math.floor(lon_min), math.floor(lon_max) + 1)

    # Build a merged grid covering the full extent
    rows_total = 0
    cols_total = 0
    tile_data = {}
    tile_size = None

    for tlat in lat_tiles:
        for tlon in lon_tiles:
            t = srtm_mgr._get_tile(tlat, tlon)
            if t is not None:
                data, sz = t
                tile_data[(tlat, tlon)] = data
                tile_size = sz
            else:
                tile_data[(tlat, tlon)] = None

    if tile_size is None:
        # No SRTM data at all — return flat grid
        return np.zeros((out_size, out_size), dtype=np.float32)

    n_lat = len(lat_tiles)
    n_lon = len(lon_tiles)
    merged = np.zeros((n_lat * tile_size, n_lon * tile_size), dtype=np.float32)

    sorted_lats = sorted(lat_tiles, reverse=True)  # top (north) first
    sorted_lons = sorted(lon_tiles)

    for ri, tlat in enumerate(sorted_lats):
        for ci, tlon in enumerate(sorted_lons):
            d = tile_data.get((tlat, tlon))
            if d is not None:
                merged[ri * tile_size:(ri + 1) * tile_size,
                       ci * tile_size:(ci + 1) * tile_size] = d

    # Map pixel coords for the requested extent
    total_lat_max = max(sorted_lats) + 1
    total_lon_min = min(sorted_lons)
    total_lat_min = min(sorted_lats)
    total_lon_max = max(sorted_lons) + 1

    # Row/col in merged array
    r_start = int((total_lat_max - lat_max) / (total_lat_max - total_lat_min) * merged.shape[0])
    r_end = int((total_lat_max - lat_min) / (total_lat_max - total_lat_min) * merged.shape[0])
    c_start = int((lon_min - total_lon_min) / (total_lon_max - total_lon_min) * merged.shape[1])
    c_end = int((lon_max - total_lon_min) / (total_lon_max - total_lon_min) * merged.shape[1])

    r_start = max(0, min(r_start, merged.shape[0] - 1))
    r_end = max(r_start + 1, min(r_end, merged.shape[0]))
    c_start = max(0, min(c_start, merged.shape[1] - 1))
    c_end = max(c_start + 1, min(c_end, merged.shape[1]))

    block = merged[r_start:r_end, c_start:c_end]
    block[block <= -32768] = 0.0

    # Resize to output size
    if block.shape[0] != out_size or block.shape[1] != out_size:
        img = _Img.fromarray(block)
        img = img.resize((out_size, out_size), _Img.BILINEAR)
        block = np.array(img, dtype=np.float32)

    return block


@app.get("/api/terrain/dem/{z}/{x}/{y}.png")
def terrain_dem_tile(z: int, x: int, y: int, mode: str = "terrain"):
    """
    Serve raster-dem tiles in Mapbox Terrain-RGB encoding for MapLibre setTerrain().
    Uses LiDAR (MNS/MNT) with SRTM fallback.
    mode: 'terrain' (DTM ground), 'surface' (DSM ground+canopy)
    Encoding: elevation = -10000 + (R*256*256 + G*256 + B) * 0.1
    """
    import io as _io
    from PIL import Image as _Image

    tile_size = 256

    # Tile bounds (Web Mercator → WGS84)
    n = 2 ** z
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    use_canopy = mode == "surface"

    # Try LiDAR block read first (fast)
    ds_type = "mnt"
    grid = None
    if hasattr(terrain, 'read_block'):
        block = terrain.read_block(lat_min, lon_min, lat_max, lon_max,
                                    dataset_type=ds_type, max_pixels=tile_size)
        if block is not None:
            grid = block[0]
            if use_canopy:
                canopy_block = terrain.read_block(lat_min, lon_min, lat_max, lon_max,
                                                   dataset_type="mhc", max_pixels=tile_size)
                if canopy_block is not None:
                    cb = canopy_block[0]
                    if cb.shape != grid.shape:
                        cb_img = _Image.fromarray(cb)
                        cb_img = cb_img.resize((grid.shape[1], grid.shape[0]), _Image.BILINEAR)
                        cb = np.array(cb_img)
                    grid = grid + np.maximum(cb, 0)

    # Fallback: SRTM direct array slicing (fast)
    if grid is None:
        grid = _srtm_block_read(srtm, lat_min, lon_min, lat_max, lon_max, tile_size)

    # Resize to tile_size if needed
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
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(buf, media_type="image/png",
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


@app.get("/api/data/buildings")
def get_buildings(lat: float, lon: float, radius_km: float = 2.0):
    """Get building footprints near a point (from downloaded data)."""
    import json
    buildings_path = os.path.join(DATA_DIR, "buildings", "quebec_city_batiments.geojson")
    if not os.path.exists(buildings_path):
        raise HTTPException(404, detail="Buildings data not downloaded. POST /api/data/download/quebec-city first.")

    with open(buildings_path) as f:
        data = json.load(f)

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

    # Pass 2: batch LiDAR height lookup via block read
    mhc_grid = None
    mhc_meta = None
    if candidates and hasattr(terrain, 'read_block'):
        all_lats = [c[1] for c in candidates]
        all_lons = [c[2] for c in candidates]
        blk_lat_min, blk_lat_max = min(all_lats), max(all_lats)
        blk_lon_min, blk_lon_max = min(all_lons), max(all_lons)
        # Add small padding
        pad = 0.001
        try:
            block = terrain.read_block(blk_lat_min - pad, blk_lon_min - pad,
                                        blk_lat_max + pad, blk_lon_max + pad,
                                        dataset_type="mhc", max_pixels=2000)
            if block is not None:
                mhc_grid, mhc_meta = block
        except Exception:
            pass

    def _sample_mhc(clat, clon):
        """Sample canopy height from block-read grid."""
        if mhc_grid is None or mhc_meta is None:
            return None
        lat_min_b = mhc_meta.get("lat_min", mhc_meta.get("south", 0))
        lat_max_b = mhc_meta.get("lat_max", mhc_meta.get("north", 0))
        lon_min_b = mhc_meta.get("lon_min", mhc_meta.get("west", 0))
        lon_max_b = mhc_meta.get("lon_max", mhc_meta.get("east", 0))
        if lat_max_b <= lat_min_b or lon_max_b <= lon_min_b:
            return None
        r = int((lat_max_b - clat) / (lat_max_b - lat_min_b) * mhc_grid.shape[0])
        c = int((clon - lon_min_b) / (lon_max_b - lon_min_b) * mhc_grid.shape[1])
        r = max(0, min(r, mhc_grid.shape[0] - 1))
        c = max(0, min(c, mhc_grid.shape[1] - 1))
        val = float(mhc_grid[r, c])
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

        # Try LiDAR canopy height
        if height is None:
            lidar_h = _sample_mhc(clat, clon)
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

    return {
        "type": "FeatureCollection",
        "features": filtered[:25000],  # Limit for performance
        "total_in_area": len(filtered),
    }
