"""MRNF carte ecoforestiere a jour — polygon forest reader.

Attributes we care about (see DICTIONNAIRE_CARTE_ECO_MAJ.xlsx):
  CL_HAUT  1..7 — stand height class (1=<2m, 2=2-4, 3=4-7, 4=7-12, 5=12-17,
                                       6=17-22, 7=>=22). Older MAJ releases
                                       only use 1..5; we accept both.
  CL_DENS  A..D — crown-cover density (A>=80%, B 60-80, C 40-60, D 25-40).
  GR_ESS  — species-group code (SEPM = conifers, BFE/BFI/ERFT = deciduous...).

The reader produces a per-polygon `atten_db_m` (specific attenuation, dB/m)
using a pragmatic ITU-R P.833-style model. Integrating this along the RF
ray path gives total vegetation loss.

Usage:
    forest = EcoforestIndex.from_default_data_dir()
    polys = forest.query_bbox(lat_min, lon_min, lat_max, lon_max)
    # or directly per-point:
    atten = forest.sample_attenuation(lat, lon, freq_mhz=915)
"""
from __future__ import annotations
import logging
import math
import os
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Height class midpoints in metres. We accept both the 5-class (older MAJ)
# and 7-class (5e inventaire) conventions — the mapping below is a union.
_HEIGHT_MIDPOINT_M = {
    1: 1.5, 2: 3.0, 3: 5.5, 4: 9.5, 5: 14.5, 6: 19.5, 7: 25.0,
}
# Crown-cover density multiplier (fraction of path actually obstructed).
_DENSITY_FRAC = {"A": 0.9, "B": 0.7, "C": 0.5, "D": 0.3}

# Specific attenuation in dB/m for a fully obstructed canopy at ~900 MHz
# (ITU-R P.833 curves, foliage in leaf). Conifers attenuate year-round;
# deciduous drop to ~0.10 dB/m in winter, not modelled here.
_SPEC_ATTEN_DB_PER_M = {"conifer": 0.40, "deciduous": 0.30, "mixed": 0.35}

# Two-letter MRNF species codes classified by foliage persistence.
# Codes in GR_ESS are typically 2- or 4-char concatenations like "ESFT" =
# "essences ES" + "FT"; we classify by scanning every 2-char window.
_CONIFER_CODES = {
    "EP", "EB", "EN", "EX", "ES", "SE", "SB", "SP", "SA", "SS", "PR", "PB",
    "PG", "PI", "PS", "PU", "ME", "MX", "TH", "RX", "RZ", "RN", "RP",
}
_DECIDUOUS_CODES = {
    "ER", "ES2", "BO", "BP", "BB", "BJ", "CH", "CT", "CR", "FA", "FT", "FN",
    "FI", "FX", "FO", "FH", "PE", "PA", "TA", "HG", "OR", "NC", "PL",
}


def _essence_type(gr_ess: str | None) -> str:
    if not gr_ess:
        return "mixed"
    code = gr_ess.strip().upper()
    # Slice the code into 2-char windows and vote
    conif = decid = 0
    for i in range(0, len(code) - 1, 2):
        c2 = code[i:i + 2]
        if c2 in _CONIFER_CODES:
            conif += 1
        elif c2 in _DECIDUOUS_CODES:
            decid += 1
    if conif and not decid:
        return "conifer"
    if decid and not conif:
        return "deciduous"
    if conif and decid:
        return "mixed"
    # Some 3-letter codes or abbreviations
    if code.startswith(("SEPM", "RES", "RX", "RZ")):
        return "conifer"
    if code.startswith(("FE", "BFE", "BFI", "ERF", "ERS")):
        return "deciduous"
    return "mixed"


def _height_m(cl_haut) -> float:
    try:
        return _HEIGHT_MIDPOINT_M.get(int(cl_haut), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _density_frac(cl_dens) -> float:
    if not cl_dens:
        return 0.0
    return _DENSITY_FRAC.get(str(cl_dens).strip().upper()[:1], 0.0)


def specific_attenuation_db_m(cl_haut, cl_dens, gr_ess,
                              freq_mhz: float = 915.0) -> float:
    """Return effective dB per metre of *horizontal* path through this stand.

    We weight the per-tree specific attenuation by density and by a crude
    canopy-presence factor derived from stand height (very short stands
    don't block a horizontal ray the same way a 22m canopy does)."""
    h = _height_m(cl_haut)
    if h <= 0:
        return 0.0
    dens = _density_frac(cl_dens)
    if dens <= 0:
        return 0.0
    spec = _SPEC_ATTEN_DB_PER_M[_essence_type(gr_ess)]
    # Frequency scaling (rough, ITU-R P.833): ~ f^0.28 around 1 GHz.
    freq_factor = (max(freq_mhz, 30.0) / 915.0) ** 0.28
    # Height factor: saturates above ~15 m (rays rarely travel fully
    # vertically through a tall canopy; cap the effect).
    h_factor = min(h / 15.0, 1.0)
    return spec * dens * h_factor * freq_factor


@dataclass
class ForestPolygon:
    cl_haut: int | None
    cl_dens: str | None
    gr_ess: str | None
    atten_db_m: float
    height_m: float
    bounds: tuple[float, float, float, float]  # (lonmin, latmin, lonmax, latmax)
    # WGS84 ring as list[(lon, lat)]; outer ring only
    ring: list[tuple[float, float]]


class EcoforestIndex:
    """Lazy spatial index over MRNF stands. Uses geopandas/fiona when available."""

    def __init__(self, gpkg_path: Path):
        self.gpkg_path = Path(gpkg_path)
        self._gdf = None

    @classmethod
    def from_default_data_dir(cls) -> "EcoforestIndex | None":
        root = Path(__file__).resolve().parents[3]
        veg_dir = root / "data" / "vegetation"
        zip_path = veg_dir / "carte_eco_21L_gpkg.zip"
        # Accept either the raw .zip (we will extract on first use) or a
        # pre-extracted .gpkg in the same folder.
        gpkg = next(veg_dir.glob("*.gpkg"), None)
        if gpkg is None and zip_path.exists():
            logger.info("Extracting ecoforest GPKG from %s", zip_path)
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".gpkg"):
                        zf.extract(name, veg_dir)
                        gpkg = veg_dir / name
                        break
        if gpkg is None or not gpkg.exists():
            logger.warning("Ecoforest GPKG not found under %s — run scripts/download_data.py",
                           veg_dir)
            return None
        return cls(gpkg)

    def _load(self):
        if self._gdf is not None:
            return self._gdf
        try:
            import geopandas as gpd
        except ImportError as e:
            logger.warning("geopandas not installed: %s", e)
            return None
        logger.info("Loading ecoforest polygons from %s ...", self.gpkg_path)
        # MRNF GPKG holds 5 layers; the actual stand polygons are in `pee_maj_*`
        # (Peuplement Ecoforestier). We pick the first layer whose name starts
        # with `pee_` so this works across feuillets.
        layer = "pee_maj_21l"
        try:
            import fiona
            layers = fiona.listlayers(str(self.gpkg_path))
            pee = [l for l in layers if l.lower().startswith("pee_")]
            if pee:
                layer = pee[0]
        except Exception:
            pass
        logger.info("  using layer: %s", layer)
        gdf = gpd.read_file(self.gpkg_path, layer=layer)
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        # Normalise attribute names — MRNF uses different casings across vintages.
        rename = {}
        for col in gdf.columns:
            low = col.lower()
            if low in ("cl_haut", "hauteur", "class_haut"):
                rename[col] = "CL_HAUT"
            elif low in ("cl_dens", "densite", "class_dens"):
                rename[col] = "CL_DENS"
            elif low in ("gr_ess", "gr_ess_car", "ess_car", "ess"):
                rename[col] = "GR_ESS"
        if rename:
            gdf = gdf.rename(columns=rename)
        self._gdf = gdf
        logger.info("Ecoforest loaded: %d polygons", len(gdf))
        return gdf

    def query_bbox(self, lat_min: float, lon_min: float,
                   lat_max: float, lon_max: float) -> list[ForestPolygon]:
        gdf = self._load()
        if gdf is None:
            return []
        # Spatial filter via bbox — uses the R-tree if available.
        sub = gdf.cx[lon_min:lon_max, lat_min:lat_max]
        out: list[ForestPolygon] = []
        for _, row in sub.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            cl_haut = row.get("CL_HAUT")
            cl_dens = row.get("CL_DENS")
            gr_ess = row.get("GR_ESS")
            atten = specific_attenuation_db_m(cl_haut, cl_dens, gr_ess)
            h = _height_m(cl_haut)
            # Flatten to the outer ring of whichever polygon part is largest.
            if geom.geom_type == "MultiPolygon":
                geom = max(geom.geoms, key=lambda g: g.area)
            if geom.geom_type != "Polygon":
                continue
            ring = [(float(x), float(y)) for x, y in geom.exterior.coords]
            out.append(ForestPolygon(
                cl_haut=int(cl_haut) if cl_haut is not None else None,
                cl_dens=str(cl_dens) if cl_dens else None,
                gr_ess=str(gr_ess) if gr_ess else None,
                atten_db_m=atten,
                height_m=h,
                bounds=tuple(geom.bounds),
                ring=ring,
            ))
        return out

    @lru_cache(maxsize=4096)
    def sample_attenuation(self, lat: float, lon: float,
                           freq_mhz: float = 915.0) -> float:
        """Return the specific attenuation (dB/m) for the stand at (lat, lon),
        or 0.0 if outside forest polygons."""
        gdf = self._load()
        if gdf is None:
            return 0.0
        from shapely.geometry import Point
        pt = Point(lon, lat)
        hit = gdf[gdf.contains(pt)]
        if hit.empty:
            return 0.0
        row = hit.iloc[0]
        return specific_attenuation_db_m(
            row.get("CL_HAUT"), row.get("CL_DENS"), row.get("GR_ESS"),
            freq_mhz=freq_mhz,
        )
