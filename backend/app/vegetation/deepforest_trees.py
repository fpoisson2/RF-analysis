"""Loader for DeepForest-detected trees.

The CMQ 2021 orthophoto pipeline (scripts/run_deepforest.py) writes
`data/vegetation/deepforest_detected.geojson`. This module exposes the
points and provides a merge helper identical in shape to
`vdq_trees.merge_with_lidar`, so the main API can chain:

    trees = _extract_trees_from_lidar(...)
    trees = vdq_trees.merge_with_lidar(trees, ...)
    trees = deepforest_trees.merge_with_lidar(trees, ...)
"""
from __future__ import annotations
import json
import logging
import math
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_PATH = (Path(__file__).resolve().parents[3]
         / "data" / "vegetation" / "deepforest_detected.geojson")


@lru_cache(maxsize=1)
def _load() -> list[dict]:
    if not _PATH.exists():
        return []
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Failed to load DeepForest GeoJSON: %s", e)
        return []
    feats = data.get("features") or []
    trees = []
    for f in feats:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        coords = g.get("coordinates") or []
        if len(coords) < 2:
            continue
        props = f.get("properties") or {}
        h = props.get("h")
        if h is None or float(h) < 2.5:
            continue
        trees.append({
            "lon": float(coords[0]), "lat": float(coords[1]),
            "h": float(h),
            "score": float(props.get("score", 0.0)),
            "crown_m": float(props.get("crown_m", 0.0)),
        })
    logger.info("Loaded DeepForest detections: %d", len(trees))
    return trees


def merge_with_lidar(lidar_features: list[dict], lat: float, lon: float,
                    radius_km: float) -> list[dict]:
    trees = _load()
    if not trees:
        return lidar_features

    cos_lat = math.cos(math.radians(lat))
    lat_r = radius_km / 111.32
    lon_r = radius_km / (111.32 * cos_lat)
    local = [t for t in trees
             if lat - lat_r <= t["lat"] <= lat + lat_r
             and lon - lon_r <= t["lon"] <= lon + lon_r]
    if not local:
        return lidar_features

    # Dedup LiDAR points within 3m of a DeepForest detection (DF gives us
    # actual crown diameter; keep it).
    dlat = 3.0 / 111320.0
    dlon = 3.0 / (111320.0 * cos_lat)
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for t in local:
        k = (int((t["lat"] - lat) / dlat), int((t["lon"] - lon) / dlon))
        grid.setdefault(k, []).append((t["lat"], t["lon"]))

    kept = []
    for feat in lidar_features:
        c = feat.get("geometry", {}).get("coordinates", [])
        if len(c) < 2:
            continue
        flon, flat = float(c[0]), float(c[1])
        if feat.get("properties", {}).get("src") in ("vdq", "deepforest"):
            kept.append(feat)
            continue
        cr = int((flat - lat) / dlat)
        cc = int((flon - lon) / dlon)
        collided = False
        for dr in (-1, 0, 1):
            if collided:
                break
            for dc in (-1, 0, 1):
                for vlat, vlon in grid.get((cr + dr, cc + dc), ()):
                    dy = (flat - vlat) * 111320.0
                    dx = (flon - vlon) * 111320.0 * cos_lat
                    if dx * dx + dy * dy < 9.0:
                        collided = True
                        break
                if collided:
                    break
        if not collided:
            kept.append(feat)

    for t in local:
        kept.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]},
            "properties": {
                "h": round(t["h"], 1),
                "src": "deepforest",
                "crown": round(t["crown_m"], 2),
            },
        })
    return kept
