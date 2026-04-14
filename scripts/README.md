# Digital-twin pipeline

Scripts that turn open Quebec City data into Unreal Engine 5 / Cesium
assets. Run in dependency order, or use `run_all.py`.

| # | Script                            | Module | Input                                         | Output                                        | Rough runtime |
|---|-----------------------------------|--------|-----------------------------------------------|-----------------------------------------------|----------------|
| 1 | `download_data.py`                | —      | (internet)                                    | `data/vegetation/*.geojson`, tile index       |  2 min         |
| 2 | `download_ortho_tiles.py`         | 3      | tile index                                    | `data/vegetation/ortho_tiles/*.tif`           | depends on km  |
| 3 | `build_heightmap.py`              | 1      | `data/lidar/quebec_city/MNT_*.tif`            | `data/unreal/heightmap/*.png` + manifest      | 10 min         |
| 4 | `build_buildings_citygml.py`      | 2      | footprint GeoJSON + MNT                       | 3D Tiles + CityGML chunks                     | 60 min         |
| 5 | `batch_deepforest.py`             | 4a     | 1497 CMQ ortho tiles (`E:/rf_analysis/…`)     | `deepforest_detected.geojson`                 | hours, GPU     |
| 6 | `merge_tree_catalog.py`           | 4b     | VdQ + DeepForest + optional LiDAR MHC         | `trees_merged.geojson` + csv                  | 5 min          |
| 7 | `export_trees_unreal_pcg.py`      | 4c     | `trees_merged.csv`                            | `data/unreal/trees/*.csv` (PCG-ready)         | 1 min          |
| 8 | `project_roof_textures.py`        | 3a     | footprints + orthophotos                      | `data/unreal/roof_textures/<shard>/<oid>.png` | 30–90 min      |
| 9 | `upscale_textures_realesrgan.py`  | 8      | roof PNGs                                     | `data/unreal/roof_textures_4x/…`              | hours, GPU     |
|10 | `fetch_mapillary.py`              | 5a     | Mapillary API (needs `MAPILLARY_TOKEN`)       | `data/street_furniture/*.geojson`             | 5–30 min       |
|11 | `run_deepforest.py`               | 4a     | single ortho tile (used internally by #5)     | appends to `deepforest_detected.geojson`      | per-tile       |

## Dependencies

```
pip install rasterio geopandas shapely pyproj pillow scipy numpy
pip install deepforest torch    # for tree detection; torch CUDA build
pip install py3dtiles           # for 3D Tiles conversion
# external:
#   3dfier   (tudelft3d/3dfier)           — CityGML LOD1 from footprints
#   realesrgan-ncnn-vulkan                — fast texture upscaling
```

## What the Unreal side has to do

The scripts stop at the "import it into Unreal" boundary. Inside UE5:

1. **Landscape** — Import `data/unreal/heightmap/*.png` via *Landscape
   Mode → Manage → Import* with the X/Y/Z scales printed by
   `build_heightmap.py`. Enable World Partition for streaming.
2. **Buildings** — Use *Cesium for Unreal* → *Add Tileset from URL* and
   point it to `data/unreal/buildings/tileset/tileset.json` (or
   Datasmith-import the OBJs directly).
3. **Trees** — Import each CSV from `data/unreal/trees/` as a DataTable,
   then a PCG Graph that reads each DT and spawns the matching species
   mesh (variants 0–7 → randomised static mesh array). SpeedTree/Grove3D
   meshes are manual.
4. **Roof textures** — Bulk-import `data/unreal/roof_textures_4x/` (UE5
   *Import Multiple Assets*), then a material that samples the texture
   using the roof's world-space XY and the oriented-bbox info from
   `_index.json` (convert to per-material params via a Python Editor
   script — UE5 supports this).
5. **Street furniture** — Import GeoJSONs from `data/street_furniture/`
   via the *Geospatial* plugin or a custom Editor utility.

## Resuming / reruns

Every script is idempotent:
- `batch_deepforest.py` keeps `data/vegetation/deepforest_batch.ckpt.json`
- `project_roof_textures.py` skips files that already exist in output
- `upscale_textures_realesrgan.py` skips files whose target exists
- `build_buildings_citygml.py` skips chunks with a non-empty `.obj` file

If you change the output format, **delete the output directory** — scripts
will not detect format changes and will happily skip stale files.

## Data layout reminder

```
data/
├── lidar/quebec_city/             MNT_*.tif, MHC_*.tif  (MRNF)
├── buildings/                     quebec_city_batiments.geojson
├── vegetation/                    VdQ + ecoforest + DeepForest outputs
├── street_furniture/              Mapillary output
└── unreal/
    ├── heightmap/                 landscape PNG16 tiles
    ├── buildings/                 CityGML + 3D Tiles
    ├── trees/                     PCG CSVs per species/bucket
    ├── roof_textures/             1k per-building roof PNGs
    └── roof_textures_4x/          4x upscaled
```
