"""Ville de Quebec municipal tree inventory loader.

Two datasets (both CC-BY, refreshed weekly):
  * vdq-arbrerepertorie.geojson      — ~104k trees
  * vdq-arbrepotentielremarquable.geojson  — remarkable-candidate trees

For each tree we have species (Latin + French), type (conifer/deciduous), and
DHP (diameter at breast height, cm). We derive height from DHP using a simple
allometric relation, and specific attenuation from type."""
from __future__ import annotations
import json
import logging
import math
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_VEG_DIR = Path(__file__).resolve().parents[3] / "data" / "vegetation"
_FILES = [
    _VEG_DIR / "vdq_arbres_repertories.geojson",
    _VEG_DIR / "vdq_arbres_remarquables.geojson",
]


def _height_from_dhp(dhp_cm: float) -> float:
    """Allometric estimate. Matches user's spec:  H = 15 * (DHP/100)^0.6.

    DHP 30 → 7.3 m, DHP 50 → 9.9 m, DHP 100 → 15 m. Reasonable for urban
    hardwoods; errs conservatively low for very old specimens."""
    try:
        d = max(float(dhp_cm), 0.0)
    except (TypeError, ValueError):
        return 0.0
    if d < 1.0:
        return 0.0
    return 15.0 * (d / 100.0) ** 0.6


def _is_conifer(props: dict) -> bool:
    for key in ("TYPE_ARBRE", "TYPE", "type", "type_arbre"):
        v = props.get(key)
        if not v:
            continue
        s = str(v).strip().lower()
        if "coni" in s or "résin" in s or "resin" in s:
            return True
        if "feuil" in s:
            return False
    # Fallback: Latin family heuristic
    latin = str(props.get("ESSENCE_LAT") or props.get("NOM_LATIN") or "").lower()
    for p in ("picea", "pinus", "abies", "larix", "thuja", "tsuga", "juniperus"):
        if p in latin:
            return True
    return False


def _extract_dhp(props: dict) -> float:
    for key in ("DIAMETRE", "DHP", "dhp", "diametre"):
        v = props.get(key)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


@lru_cache(maxsize=1)
def _load_all() -> list[dict]:
    """Return a flat list of normalised tree dicts:
        {lon, lat, h, dhp, conifer, atten_db_m, species}"""
    trees: list[dict] = []
    for path in _FILES:
        if not path.exists():
            logger.info("VdQ inventory missing: %s", path.name)
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Failed to load %s: %s", path, e)
            continue
        feats = data.get("features") or []
        for feat in feats:
            g = feat.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            coords = g.get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            props = feat.get("properties") or {}
            dhp = _extract_dhp(props)
            h = _height_from_dhp(dhp)
            if h < 1.5:
                # Without a usable height we can't put a tree in the 3D scene
                # or in the RF attenuation budget — skip.
                continue
            conifer = _is_conifer(props)
            spec = 0.40 if conifer else 0.30
            trees.append({
                "lon": lon, "lat": lat, "h": round(h, 1),
                "dhp": dhp, "conifer": conifer,
                "atten_db_m": spec,
                "species": props.get("ESSENCE_LAT") or props.get("NOM_LATIN")
                           or props.get("NOM_COMMUN") or "",
            })
        logger.info("Loaded %s: %d trees (cumulative %d)", path.name, len(feats), len(trees))
    return trees


def query_bbox(lat_min: float, lon_min: float,
               lat_max: float, lon_max: float) -> list[dict]:
    out = []
    for t in _load_all():
        if lat_min <= t["lat"] <= lat_max and lon_min <= t["lon"] <= lon_max:
            out.append(t)
    return out


def merge_with_lidar(lidar_features: list[dict], lat: float, lon: float,
                    radius_km: float) -> list[dict]:
    """Return a list of tree features, deduped.

    Any LiDAR-detected tree within ~3 m of a VdQ tree is discarded (VdQ wins,
    since we have species + measured DHP). Then VdQ trees inside the bbox are
    appended as features matching the LiDAR format with extra properties."""
    cos_lat = math.cos(math.radians(lat))
    lat_r = radius_km / 111.32
    lon_r = radius_km / (111.32 * cos_lat)
    vdq = query_bbox(lat - lat_r, lon - lon_r, lat + lat_r, lon + lon_r)
    if not vdq:
        return lidar_features

    # Build a coarse spatial grid on VdQ trees for O(n+m) dedup
    # Cell ~3 m: dlat=3/111320, dlon=3/(111320*cos_lat)
    dlat = 3.0 / 111320.0
    dlon = 3.0 / (111320.0 * cos_lat)
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for t in vdq:
        key = (int((t["lat"] - lat) / dlat), int((t["lon"] - lon) / dlon))
        grid.setdefault(key, []).append((t["lat"], t["lon"]))

    kept = []
    for feat in lidar_features:
        c = feat.get("geometry", {}).get("coordinates", [])
        if len(c) < 2:
            continue
        flon, flat = float(c[0]), float(c[1])
        # Check the cell and its 8 neighbours (~3m radius)
        cr = int((flat - lat) / dlat)
        cc = int((flon - lon) / dlon)
        collided = False
        for dr in (-1, 0, 1):
            if collided:
                break
            for dc in (-1, 0, 1):
                for vlat, vlon in grid.get((cr + dr, cc + dc), ()):
                    # Haversine-free distance (small angles): convert to metres
                    dy = (flat - vlat) * 111320.0
                    dx = (flon - vlon) * 111320.0 * cos_lat
                    if dx * dx + dy * dy < 9.0:  # 3 m^2
                        collided = True
                        break
                if collided:
                    break
        if not collided:
            kept.append(feat)

    # Append VdQ trees as features
    for t in vdq:
        kept.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]},
            "properties": {
                "h": t["h"],
                "src": "vdq",
                "sp": t["species"],
                "c": 1 if t["conifer"] else 0,
                "a": t["atten_db_m"],
            },
        })
    return kept
