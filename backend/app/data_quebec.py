"""
Quebec open data sources integration.

Sources:
- Données Québec (donneesquebec.ca)
  - LiDAR coverage for most of southern Quebec
  - Modèle numérique de terrain (MNT) / DTM
  - Modèle numérique de surface (MNS) / DSM

- Ville de Québec (donnees.ville.quebec.qc.ca)
  - Empreintes de bâtiments 3D avec hauteurs
  - Arbres publics (position + hauteur + espèce)
  - Zones de végétation

- Ville de Montréal (donnees.montreal.ca)
  - Bâtiments 2D et 3D
  - Canopée urbaine
  - Modèle numérique de surface LiDAR

- MERN (Ministère de l'Énergie et des Ressources naturelles)
  - Modèle numérique du terrain du Québec (MNTQ)
  - Données géodésiques

- Forêt ouverte (forestsouverts.gouv.qc.ca)
  - Carte écoforestière (hauteur des arbres, type de peuplement)
  - Inventaire forestier
"""
import json
import logging
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request

logger = logging.getLogger(__name__)


# ── Données Québec API endpoints ─────────────────────────────────────

QUEBEC_DATA_SOURCES = {
    "ville_quebec_batiments": {
        "name": "Bâtiments 3D - Ville de Québec",
        "description": "Empreintes de bâtiments avec hauteurs pour la Ville de Québec",
        "url": "https://donnees.ville.quebec.qc.ca/dataset/empreintes-des-batiments",
        "format": "GeoJSON / SHP",
        "has_heights": True,
        "api_url": "https://donnees.ville.quebec.qc.ca/dataset/empreintes-des-batiments/resource/json",
    },
    "ville_quebec_arbres": {
        "name": "Arbres publics - Ville de Québec",
        "description": "Position, espèce et dimensions des arbres publics",
        "url": "https://donnees.ville.quebec.qc.ca/dataset/arbres",
        "format": "CSV / GeoJSON",
        "has_heights": True,
    },
    "montreal_batiments": {
        "name": "Bâtiments 2D - Ville de Montréal",
        "description": "Empreintes de bâtiments pour Montréal",
        "url": "https://donnees.montreal.ca/dataset/batiment-2d",
        "format": "GeoJSON / SHP",
        "has_heights": False,  # Need LiDAR DSM-DTM for heights
    },
    "montreal_lidar": {
        "name": "LiDAR - Ville de Montréal",
        "description": "Modèle numérique de surface LiDAR",
        "url": "https://donnees.montreal.ca/dataset/modele-numerique-de-surface",
        "format": "GeoTIFF",
        "has_heights": True,
    },
    "quebec_lidar": {
        "name": "LiDAR aéroporté - Données Québec",
        "description": "Couverture LiDAR du territoire québécois (MERN)",
        "url": "https://www.donneesquebec.ca/recherche/dataset/produits-derives-de-base-du-lidar",
        "format": "GeoTIFF / LAZ",
        "has_heights": True,
    },
    "forets_ouvertes": {
        "name": "Carte écoforestière - Forêts ouvertes",
        "description": "Hauteur du couvert forestier, type de peuplement, densité",
        "url": "https://www.foretouverte.gouv.qc.ca/",
        "format": "WMS / WFS",
        "has_heights": True,
        "wms_url": "https://serviceswebcarto.mffp.gouv.qc.ca/pes/services/Inventaire/CARTE_ECOFOR/MapServer/WMSServer",
    },
    "mern_mnt": {
        "name": "Modèle numérique du terrain - MERN",
        "description": "MNT haute résolution du Québec",
        "url": "https://www.donneesquebec.ca/recherche/dataset/modele-numerique-de-terrain",
        "format": "GeoTIFF",
        "has_heights": True,
    },
}


class QuebecDataManager:
    """Manager for Quebec-specific open data sources."""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.quebec_dir = self.data_dir / "quebec"
        self.quebec_dir.mkdir(parents=True, exist_ok=True)

    def list_sources(self) -> list[dict]:
        """List all available Quebec data sources."""
        return [
            {"id": k, **v} for k, v in QUEBEC_DATA_SOURCES.items()
        ]

    def get_source_status(self) -> dict:
        """Check which data sources have been downloaded."""
        status = {}
        for source_id, info in QUEBEC_DATA_SOURCES.items():
            source_dir = self.quebec_dir / source_id
            if source_dir.exists():
                files = list(source_dir.iterdir())
                status[source_id] = {
                    "name": info["name"],
                    "downloaded": True,
                    "files": len(files),
                    "size_mb": sum(f.stat().st_size for f in files if f.is_file()) / 1e6,
                }
            else:
                status[source_id] = {
                    "name": info["name"],
                    "downloaded": False,
                }
        return status

    def download_ville_quebec_batiments(self) -> Optional[Path]:
        """
        Download building footprints from Ville de Québec open data.
        These include building heights which is very valuable for RF planning.
        """
        output_dir = self.quebec_dir / "ville_quebec_batiments"
        output_dir.mkdir(exist_ok=True)
        geojson_path = output_dir / "batiments.geojson"

        if geojson_path.exists():
            logger.info("Ville de Québec buildings data already downloaded")
            return geojson_path

        # The actual download URL for the GeoJSON format
        # Note: This URL may change - check donnees.ville.quebec.qc.ca for current link
        urls_to_try = [
            "https://donnees.ville.quebec.qc.ca/handler.ashx?id=37d63e50-d918-4e41-8c60-3569f0a2ca28&f=geojson",
            "https://donnees.ville.quebec.qc.ca/dataset/empreintes-des-batiments",
        ]

        for url in urls_to_try:
            try:
                logger.info(f"Downloading Ville de Québec buildings from {url}...")
                req = Request(url, headers={"User-Agent": "RF-Planner/1.0"})
                response = urlopen(req, timeout=120)
                data = response.read()

                # Try to parse as GeoJSON
                try:
                    geojson = json.loads(data)
                    if "features" in geojson:
                        with open(geojson_path, "w") as f:
                            json.dump(geojson, f)
                        logger.info(f"Downloaded {len(geojson['features'])} buildings")
                        return geojson_path
                except json.JSONDecodeError:
                    logger.warning(f"Response from {url} is not valid GeoJSON")
                    continue
            except Exception as e:
                logger.warning(f"Failed to download from {url}: {e}")
                continue

        logger.error("Could not download Ville de Québec buildings data")
        logger.info("Please download manually from: https://donnees.ville.quebec.qc.ca/dataset/empreintes-des-batiments")
        return None

    def download_ville_quebec_arbres(self) -> Optional[Path]:
        """Download public trees data from Ville de Québec."""
        output_dir = self.quebec_dir / "ville_quebec_arbres"
        output_dir.mkdir(exist_ok=True)
        csv_path = output_dir / "arbres.csv"

        if csv_path.exists():
            logger.info("Ville de Québec trees data already downloaded")
            return csv_path

        try:
            url = "https://donnees.ville.quebec.qc.ca/handler.ashx?id=e5c7e1e6-d9b0-4e5e-beb5-9a9589c5dbb3&f=csv"
            logger.info("Downloading Ville de Québec trees...")
            req = Request(url, headers={"User-Agent": "RF-Planner/1.0"})
            response = urlopen(req, timeout=120)
            data = response.read()
            with open(csv_path, "wb") as f:
                f.write(data)
            logger.info(f"Downloaded trees data ({len(data)} bytes)")
            return csv_path
        except Exception as e:
            logger.error(f"Failed to download trees data: {e}")
            return None

    def parse_quebec_buildings(self, geojson_path: Path) -> list[dict]:
        """
        Parse Ville de Québec building footprints GeoJSON.
        Extracts building heights when available.
        """
        with open(geojson_path) as f:
            data = json.load(f)

        buildings = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            geom = feature.get("geometry", {})

            # Try to extract height from various property names
            height = None
            for h_field in ["HAUTEUR", "hauteur", "HEIGHT", "height",
                           "HAUTEUR_M", "ELEV_TOIT", "Z_MAX", "HAUT_TOIT"]:
                if h_field in props and props[h_field]:
                    try:
                        height = float(props[h_field])
                        break
                    except (ValueError, TypeError):
                        continue

            # Try to get number of floors
            if height is None:
                for f_field in ["NB_ETAGES", "ETAGES", "FLOORS", "nb_etages"]:
                    if f_field in props and props[f_field]:
                        try:
                            height = float(props[f_field]) * 3.0
                            break
                        except (ValueError, TypeError):
                            continue

            if height is None:
                height = 8.0  # Default

            # Get centroid from geometry
            coords = geom.get("coordinates", [])
            if geom.get("type") == "Polygon" and coords:
                ring = coords[0]
                lats = [p[1] for p in ring]
                lons = [p[0] for p in ring]
                centroid = [sum(lats) / len(lats), sum(lons) / len(lons)]
            elif geom.get("type") == "MultiPolygon" and coords:
                ring = coords[0][0]
                lats = [p[1] for p in ring]
                lons = [p[0] for p in ring]
                centroid = [sum(lats) / len(lats), sum(lons) / len(lons)]
            else:
                continue

            buildings.append({
                "height": height,
                "centroid": centroid,
                "type": props.get("USAGE", props.get("TYPE", "building")),
                "coords": coords,
                "source": "ville_quebec",
            })

        return buildings

    def get_foret_ouverte_wms_url(self, bbox: tuple, width: int = 512, height: int = 512) -> str:
        """
        Generate WMS URL for Forêt ouverte eco-forest map.
        Returns URL for a map tile showing forest cover.
        """
        west, south, east, north = bbox
        base_url = QUEBEC_DATA_SOURCES["forets_ouvertes"]["wms_url"]
        return (
            f"{base_url}?"
            f"SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
            f"&LAYERS=0"
            f"&CRS=EPSG:4326"
            f"&BBOX={south},{west},{north},{east}"
            f"&WIDTH={width}&HEIGHT={height}"
            f"&FORMAT=image/png"
            f"&TRANSPARENT=true"
        )
