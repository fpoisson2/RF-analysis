# Data

Source assets are not checked into git. Use `scripts/fetch_data.py` to populate.

## Layout

```
data/
  buildings/quebec_city_batiments.geojson     ~165 MB   VDQ — donneesquebec.ca
  lidar/quebec_city/MNT_21L1{3,4}{NE,NO,SE,SO}.tif   ~6.5 GB   MERN — Forêt ouverte
  lidar/quebec_city/MHC_21L1{3,4}{NE,NO,SE,SO}.tif   ~6.5 GB   MERN — Forêt ouverte
  output/                                      generated caches (scene, trees, buildings, dem)
```

## How to populate

### From a local backup (fastest)

```bash
python scripts/fetch_data.py --from-backup E:/rf_analysis/data_backup
```
Uses symlinks on platforms that allow it, otherwise copies.

### From GitHub Release (public)

```bash
python scripts/fetch_data.py --from-release
```
Downloads the buildings GeoJSON from the `data-v1` release of this repo.
**LiDAR tiles (~13 GB) are not hosted on GitHub** — grab them manually from
<https://www.foretouverte.gouv.qc.ca/> (MNT + MHC, feuillets 21L13 et 21L14).

## Publishing the buildings asset to a Release

One-time, from a machine that has the file:

```bash
gzip -k data/buildings/quebec_city_batiments.geojson
gh release create data-v1 data/buildings/quebec_city_batiments.geojson.gz \
    --title "Data assets v1" --notes "VDQ buildings footprints (gzipped)"
```

## After populating

Clear stale caches so they rebuild from the fresh sources:

```bash
rm -rf data/output/{scene_cache,trees_cache,buildings_cache,dem_cache}
```
