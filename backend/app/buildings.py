"""
Building height data manager.

Sources for building heights in Quebec:
1. OpenStreetMap (OSM) - building:levels, height tags
2. LiDAR DSM - DTM difference (Données Québec)
3. Microsoft Building Footprints (geometry only, no heights)
4. Default height estimation by building type

Strategy:
- Use OSM heights when available (most accurate for tagged buildings)
- Use LiDAR DSM-DTM difference when LiDAR is available
- Fall back to default height estimates based on land use
"""
import json
import math
import logging
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request

import numpy as np

logger = logging.getLogger(__name__)


# Default building heights by OSM building type
DEFAULT_HEIGHTS = {
    "residential": 8,       # ~2.5 floors
    "apartments": 15,       # ~5 floors
    "house": 7,             # ~2 floors
    "detached": 7,
    "commercial": 10,       # ~3 floors
    "retail": 5,            # ~1.5 floors
    "office": 25,           # ~8 floors
    "industrial": 8,
    "warehouse": 6,
    "church": 15,
    "cathedral": 30,
    "school": 10,
    "university": 15,
    "hospital": 20,
    "hotel": 20,
    "garage": 3,
    "shed": 3,
    "roof": 4,
    "yes": 8,               # Generic building
}

METERS_PER_FLOOR = 3.0


class BuildingManager:
    """Manages building footprints and heights from multiple sources."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.buildings_dir = self.data_dir / "buildings"
        self.buildings_dir.mkdir(parents=True, exist_ok=True)
        self._cache = {}

    def query_osm_buildings(self, lat: float, lon: float,
                             radius_m: float = 5000) -> list[dict]:
        """
        Query OpenStreetMap Overpass API for buildings with heights.
        Returns list of buildings with geometry and height.
        """
        cache_key = f"{lat:.3f}_{lon:.3f}_{radius_m:.0f}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Check disk cache
        cache_path = self.buildings_dir / f"osm_{cache_key}.json"
        if cache_path.exists():
            with open(cache_path) as f:
                data = json.load(f)
                self._cache[cache_key] = data
                return data

        overpass_query = f"""
        [out:json][timeout:60];
        (
          way["building"](around:{radius_m},{lat},{lon});
          relation["building"](around:{radius_m},{lat},{lon});
        );
        out body;
        >;
        out skel qt;
        """

        try:
            url = "https://overpass-api.de/api/interpreter"
            req = Request(url, data=f"data={overpass_query}".encode(),
                         headers={"User-Agent": "RF-Planner/1.0"})
            response = urlopen(req, timeout=60)
            raw = json.loads(response.read())

            buildings = self._parse_osm_response(raw)
            logger.info(f"Found {len(buildings)} buildings near {lat:.4f}, {lon:.4f}")

            # Cache to disk
            with open(cache_path, "w") as f:
                json.dump(buildings, f)
            self._cache[cache_key] = buildings
            return buildings
        except Exception as e:
            logger.warning(f"OSM query failed: {e}")
            return []

    def _parse_osm_response(self, data: dict) -> list[dict]:
        """Parse Overpass API response into building records."""
        nodes = {}
        buildings = []

        for element in data.get("elements", []):
            if element["type"] == "node":
                nodes[element["id"]] = (element["lat"], element["lon"])

        for element in data.get("elements", []):
            if element["type"] != "way":
                continue
            tags = element.get("tags", {})
            if "building" not in tags:
                continue

            # Get building polygon
            coords = []
            for nd_id in element.get("nodes", []):
                if nd_id in nodes:
                    coords.append(nodes[nd_id])
            if len(coords) < 3:
                continue

            # Determine height
            height = self._estimate_height(tags)

            # Compute centroid
            lats = [c[0] for c in coords]
            lons = [c[1] for c in coords]
            centroid_lat = sum(lats) / len(lats)
            centroid_lon = sum(lons) / len(lons)

            buildings.append({
                "id": element["id"],
                "type": tags.get("building", "yes"),
                "height": height,
                "levels": tags.get("building:levels"),
                "coords": coords,
                "centroid": [centroid_lat, centroid_lon],
                "source": "osm",
            })

        return buildings

    def _estimate_height(self, tags: dict) -> float:
        """Estimate building height from OSM tags."""
        # Direct height tag
        if "height" in tags:
            try:
                h = tags["height"].replace("m", "").strip()
                return float(h)
            except (ValueError, AttributeError):
                pass

        # Levels tag
        if "building:levels" in tags:
            try:
                levels = float(tags["building:levels"])
                return levels * METERS_PER_FLOOR
            except (ValueError, AttributeError):
                pass

        # Default by building type
        building_type = tags.get("building", "yes")
        return DEFAULT_HEIGHTS.get(building_type, 8.0)

    def get_building_attenuation_along_path(
        self, lat1: float, lon1: float, lat2: float, lon2: float,
        buildings: list[dict], attenuation_db_m: float = 0.4
    ) -> list[dict]:
        """
        Calculate building intersections and attenuation along a path.
        Returns list of obstacles with distance, height, and attenuation.
        """
        obstacles = []
        for bldg in buildings:
            # Simple check: does the building centroid fall near the path?
            clat, clon = bldg["centroid"]
            dist_to_path = self._point_to_line_distance(
                clat, clon, lat1, lon1, lat2, lon2
            )
            # Building radius estimate (assuming ~15m typical)
            bldg_radius = 15.0

            if dist_to_path < bldg_radius:
                # Calculate distance from tx to building
                dist_from_tx = self._haversine(lat1, lon1, clat, clon)
                depth = min(2 * bldg_radius, bldg_radius * 2 - dist_to_path)
                loss_db = depth * attenuation_db_m

                obstacles.append({
                    "distance_m": dist_from_tx,
                    "height_m": bldg["height"],
                    "depth_m": depth,
                    "loss_db": loss_db,
                    "type": bldg["type"],
                })

        return sorted(obstacles, key=lambda x: x["distance_m"])

    def _point_to_line_distance(self, plat, plon, lat1, lon1, lat2, lon2) -> float:
        """Approximate distance from point to line in meters."""
        # Convert to flat coordinates (good enough for short distances)
        cos_lat = math.cos(math.radians(plat))
        x = (plon - lon1) * cos_lat * 111320
        y = (plat - lat1) * 111320
        x2 = (lon2 - lon1) * cos_lat * 111320
        y2 = (lat2 - lat1) * 111320

        line_len_sq = x2 * x2 + y2 * y2
        if line_len_sq < 1e-10:
            return math.sqrt(x * x + y * y)

        t = max(0, min(1, (x * x2 + y * y2) / line_len_sq))
        proj_x = t * x2
        proj_y = t * y2
        return math.sqrt((x - proj_x) ** 2 + (y - proj_y) ** 2)

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        """Distance in meters between two points."""
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def get_buildings_grid(self, lat_center: float, lon_center: float,
                           radius_km: float, resolution_m: float,
                           buildings: list[dict]) -> np.ndarray:
        """
        Create a grid of building heights for coverage calculation.
        Returns 2D array where each cell contains the building height (0 if no building).
        """
        # Grid dimensions
        n_cells = int(2 * radius_km * 1000 / resolution_m)
        grid = np.zeros((n_cells, n_cells), dtype=np.float32)

        cos_lat = math.cos(math.radians(lat_center))
        lat_per_m = 1.0 / 111320
        lon_per_m = 1.0 / (111320 * cos_lat)

        lat_min = lat_center - radius_km * 1000 * lat_per_m
        lon_min = lon_center - radius_km * 1000 * lon_per_m

        for bldg in buildings:
            clat, clon = bldg["centroid"]
            # Grid position
            row = int((clat - lat_min) / (resolution_m * lat_per_m))
            col = int((clon - lon_min) / (resolution_m * lon_per_m))

            # Fill a small area around the centroid (approximate building footprint)
            bldg_cells = max(1, int(15.0 / resolution_m))  # ~15m building
            for dr in range(-bldg_cells, bldg_cells + 1):
                for dc in range(-bldg_cells, bldg_cells + 1):
                    r, c = row + dr, col + dc
                    if 0 <= r < n_cells and 0 <= c < n_cells:
                        grid[r, c] = max(grid[r, c], bldg["height"])

        return grid
