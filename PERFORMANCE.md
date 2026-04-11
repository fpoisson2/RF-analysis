# Propositions d'amélioration de performances

## État actuel

- **Bâtiments** : ~200k polygones GeoJSON chargés en une requête (~8MB gzippé), rendus en fill-extrusion MapLibre
- **Terrain 3D** : Tuiles AWS Terrarium (CDN, ~50ms/tuile) + hillshade
- **Couverture RF** : Grid 666x666, servi en tuiles raster 512px avec recolorisation depuis le grid brut
- **Backend** : 4 workers uvicorn, GPU CUDA pour la diffraction
- **Chrome** : WebGL via ANGLE/D3D11 — nécessite `--ignore-gpu-blocklist` pour RTX 5070 Ti

---

## 1. Bâtiments — Chargement

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Haute | **Pré-générer des tuiles vectorielles (MVT/PMTiles)** avec tippecanoe | Chargement instantané, pas de JSON 8MB à parser | Moyen |
| Haute | **Servir en Protocol Buffers** au lieu de GeoJSON | ~5x plus petit, parsing 10x plus rapide | Moyen |
| Moyenne | **Web Worker** pour parser le GeoJSON hors du thread principal | Pas de freeze UI pendant le chargement | Faible |
| Moyenne | **Charger progressivement** par distance (proche d'abord, lointain ensuite) | UI interactive immédiatement | Moyen |

### Tuiles vectorielles (recommandé)
```bash
# Installer tippecanoe
# Convertir le GeoJSON en PMTiles
tippecanoe -o buildings.pmtiles -z14 -Z10 --drop-densest-as-needed buildings.geojson

# Servir avec PMTiles protocol dans MapLibre
```
Avantage : MapLibre charge seulement les tuiles visibles. Pas de GeoJSON 8MB.

---

## 2. Bâtiments — Rendu

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Haute | **LOD (Level of Detail)** : simplifier les géométries quand dézoomé | 3-5x FPS à zoom <13 | Moyen |
| Moyenne | **deck.gl SolidPolygonLayer** avec données binaires | Instanced rendering, meilleur GPU utilization | Moyen |
| Basse | **WebGPU** (quand MapLibre le supportera) | 2-10x vs WebGL | Attendre support |

### LOD avec tippecanoe
```bash
tippecanoe -o buildings.pmtiles \
  -z14 -Z10 \
  --simplification=10 \        # Simplifier à bas zoom
  --drop-smallest-as-needed \  # Enlever les petits bâtiments à bas zoom
  --minimum-zoom-feature=12 \  # Garages seulement à zoom 12+
```

---

## 3. Couverture RF — Calcul

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Haute | **Augmenter la résolution GPU** : passer de 666x666 à 2000x2000 | Meilleure qualité sans perte de vitesse (GPU) | Faible |
| Haute | **Multi-GPU** : utiliser tous les GPU disponibles | 2x+ pour systèmes multi-GPU | Moyen |
| Moyenne | **Cache de profils terrain** : mémoriser les profils déjà calculés | Recalcul 2-3x plus rapide après le premier | Moyen |
| Moyenne | **Calcul incrémental** : quand seule la puissance change, pas besoin de recalculer la diffraction | 5-10x plus rapide pour ajustements | Élevé |

### Résolution GPU
Le RTX 5070 Ti peut facilement traiter 4000x4000 grids. Augmenter `MAX_CELLS` :
```python
# engine.py
MAX_CELLS = 4000  # au lieu de ~1000
```

---

## 4. Couverture RF — Affichage

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Haute | **Pré-découper en tuiles** à la génération au lieu de à la demande | Éliminer le flickering, réponse instantanée | Moyen |
| Moyenne | **Encoder en WebP** au lieu de PNG | 2-3x plus petit, même qualité | Faible |
| Moyenne | **Style-based coloring** : servir les valeurs brutes en raster-dem et coloriser via MapLibre expressions | Changement de palette instantané sans recalcul | Élevé |

### Pré-découpe des tuiles
```python
# Après le calcul de couverture, pré-générer toutes les tuiles nécessaires
for z in range(8, 16):
    for x, y in tiles_in_bounds(z, bounds):
        generate_and_cache_tile(z, x, y, raw_grid, bounds)
```

---

## 5. Terrain — DEM

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Basse | **Héberger nos propres tuiles DEM** (LiDAR haute-res) sur un CDN | Meilleure résolution que SRTM 30m | Élevé |
| Basse | **MBTiles/PMTiles** pour les tuiles DEM locales | Pas de dépendance à AWS | Moyen |

---

## 6. Backend — Architecture

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Haute | **Async workers** (uvicorn avec `--workers` + async endpoints) | Meilleure concurrence | Faible |
| Moyenne | **Redis cache** pour les résultats de couverture entre workers | Pas de re-lecture disque | Moyen |
| Moyenne | **Tâches en arrière-plan** (Celery/dramatiq) pour les longs calculs | UI non bloquée | Élevé |
| Basse | **gRPC** au lieu de REST pour les échanges binaires | Moins d'overhead sérialisation | Élevé |

---

## 7. Frontend — Optimisations

| Priorité | Amélioration | Gain estimé | Effort |
|----------|-------------|-------------|--------|
| Haute | **requestAnimationFrame** throttling pour les updates de couche | Moins de re-renders | Faible |
| Moyenne | **SharedArrayBuffer** + Web Worker pour le parsing GeoJSON | Parser hors thread principal | Moyen |
| Moyenne | **Offscreen Canvas** pour le sampling de couverture | Pas de blocage UI | Faible |

---

## 8. Quick wins (< 1 jour d'effort)

1. **Activer la compression Brotli** en plus de gzip (20% plus petit)
2. **HTTP/2** via un reverse proxy nginx (multiplexage des requêtes de tuiles)
3. **Service Worker** pour cache offline des tuiles terrain/bâtiments
4. **`will-change: transform`** sur le canvas MapLibre pour hinting GPU
5. **Limiter le framerate** à 60fps au lieu de 240fps (écran 240Hz = travail inutile)

---

## Ordre de priorité recommandé

1. Pré-générer les tuiles de couverture (élimine flickering)
2. PMTiles pour les bâtiments (élimine le chargement GeoJSON lourd)
3. Augmenter la résolution GPU à 2000-4000px
4. LOD pour les bâtiments (performance à bas zoom)
5. HTTP/2 + Service Worker (cache offline)
