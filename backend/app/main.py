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

    filtered = []
    for feature in data.get("features", []):
        geom = feature.get("geometry")
        if geom is None:
            continue
        coords = geom.get("coordinates", [])

        # Get centroid
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
                # Add height info
                props = feature.get("properties", {})
                height = None
                for hk in ["ELEVATION", "HAUTEUR", "hauteur", "HEIGHT", "NB_ETAGES"]:
                    if hk in props and props[hk]:
                        try:
                            val = float(props[hk])
                            height = val if hk != "NB_ETAGES" else val * 3.0
                            break
                        except (ValueError, TypeError):
                            pass
                if height is None:
                    height = 8.0

                filtered.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": {**props, "_height": height},
                })
        except (IndexError, KeyError, TypeError):
            continue

    return {
        "type": "FeatureCollection",
        "features": filtered[:10000],  # Limit for performance
        "total_in_area": len(filtered),
    }
