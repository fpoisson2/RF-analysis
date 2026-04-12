# RF Coverage Analysis — Claude Agent Guide

3D RF propagation analysis tool for Quebec. Computes radio signal coverage over LiDAR-enhanced terrain, visualized in a photorealistic 3D city model with buildings and trees.

## Architecture

**Frontend** (Vite + React + TypeScript + Tailwind + CesiumJS)
- `frontend/src/components/Map.tsx` — Main map component, same `MapProps` interface as original MapLibre version
- `frontend/src/components/cesium/` — CesiumJS modules
- `frontend/src/components/Sidebar.tsx`, `Console.tsx` — RF parameters UI + log
- `frontend/src/api/client.ts` — Backend API client
- `frontend/public/cesium/` — Cesium static assets (Workers, Assets, ThirdParty, Widgets) copied from node_modules; required for runtime

**Backend** (Python FastAPI)
- `backend/app/main.py` — All endpoints, scene serialization, tree detection
- `backend/app/terrain/lidar_terrain.py` — LiDAR MNT/MHC reader
- `backend/app/coverage/engine.py` — CUDA GPU propagation engine
- CUDA acceleration via CuPy for ITM/deygout94

**Data location** (NOT in backend/output — common mistake)
- `data/output/scene_cache/` — binary SC3D files cached per (lat, lon, radius)
- `data/output/trees_cache/`, `data/output/buildings_cache/`, `data/output/dem_cache/` — endpoint caches
- `data/buildings/quebec_city_batiments.geojson` — 200k building footprints
- `data/lidar/` — LiDAR MNT + MHC GeoTIFFs from MERN Quebec

## Running

```bash
# Backend (port 8000)
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (port 3000, proxies /api to 8000)
cd frontend && npm run dev
```

## Binary Scene Format (`/api/data/scene`)

Compact binary for fast transfer of buildings + trees. Used by `frontend/src/components/cesium/SceneLoader.ts`.

```
[magic: "SC3D" 4 bytes]
[n_bldg: uint32 LE]
[n_trees: uint32 LE]
[server_ms: float32 LE]

per building (n_bldg times):
  [n_verts: uint16 LE]
  [height: float32 LE]       — building height (m)
  [ground_z: float32 LE]     — terrain elevation at centroid (m, from LiDAR MNT)
  [lon, lat: float32 x 2]*n_verts — polygon ring

per tree (n_trees times):
  [lon, lat: float32 x 2]
  [height: float32 LE]       — tree height (m)
  [ground_z: float32 LE]     — terrain elevation at tree base (m)
```

**Important**: The backend writes the **actual** count of serialized buildings/trees into the header (after filtering degenerate polygons), not `len(features)`. The header is patched with `struct.pack_into` after serialization. See `get_scene()` in `backend/app/main.py`.

## 3D Rendering (CesiumJS)

**Terrain** — `frontend/src/components/cesium/TerrainProvider.ts`
- `CustomHeightmapTerrainProvider` decoding AWS Terrarium PNG tiles (global coverage)
- URL: `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
- Levels 6–15 fetched; > 15 bilinear-upsampled from level 15 parent tile
- Terrarium encoding: `height = (R*256 + G + B/256) - 32768`
- Vertical exaggeration: 1.5x

**Base imagery** — `frontend/src/components/cesium/BaseImagery.ts`
- Dark mode: CARTO `dark_all` with subdomains a-d for load balancing
- Light mode: OpenStreetMap via `Cesium.OpenStreetMapImageryProvider`

**Buildings** — `frontend/src/components/cesium/BuildingsMesh.ts`
- `Cesium.PolygonGeometry` + `GeometryInstance`, chunked at 5000 buildings per Primitive
- Uses `ground_z * 1.5` from binary scene for terrain placement (no client-side terrain sampling)
- `height: ground_z` + `extrudedHeight: ground_z + h * 1.5`
- Per-instance color via `ColorGeometryInstanceAttribute` (signal-based recoloring recreates primitives)

**Trees** — `frontend/src/components/cesium/TreesMesh.ts`
- **Merged geometry** buffers for scale (2M+ trees). One `Cesium.Primitive` per 50k trees
- 6-slice tapered cone (canopy only, no trunk for perf)
- Each tree: ENU transform at `(lon, lat, ground_z * 1.5 + trunk_height)`, template vertices transformed to world Cartesian3
- Per-vertex colors with vertical shading

**Viewer** — `frontend/src/components/cesium/CesiumViewer.ts`
- `depthTestAgainstTerrain = false` so buildings/trees remain visible at any zoom
- No Cesium Ion token (`Ion.defaultAccessToken = ''`)
- `CESIUM_BASE_URL = '/cesium/'` set via `vite.config.ts` `define`

## Critical gotchas

**Cesium static assets** — `vite-plugin-cesium` is unreliable; assets are copied manually to `frontend/public/cesium/` and `CESIUM_BASE_URL` is defined in `vite.config.ts`. If you see `SyntaxError: Unexpected token '<', "<!DOCTYPE ..."` from JSON parsing, it means Cesium is trying to load an asset (e.g. `approximateTerrainHeights.json`, IAU2006_XYS data) and getting Vite's HTML fallback.

**Scene cache invalidation** — If you change the binary format in `get_scene()`, you must delete `data/output/scene_cache/` or users will get stale old-format data that the frontend fails to parse (DataView out-of-bounds errors).

**Tree/building placement** — Buildings and trees MUST include `ground_z` in the binary scene. Client-side `sampleTerrainMostDetailed` does not work reliably with `CustomHeightmapTerrainProvider`. The backend samples `terrain.get_elevation()` once at scene generation.

**Building height count bug (historical)** — The old scene serializer wrote `len(bldg_features)` to the header but skipped malformed buildings with `continue`. This caused DataView out-of-bounds on the frontend. Fix: count actual serialized buildings and patch header with `struct.pack_into`.

**HTTP cache** — Scene endpoint has `Cache-Control: public, max-age=300`. If you update the format, users must hard-reload (Ctrl+Shift+R).

## Tree detection resolution

`_extract_trees_from_lidar()` in `backend/app/main.py`:
- `max_px = min(10000, radius_km * 500)` — LiDAR read resolution (~2m/pixel)
- `cell_m = 3.0` — tree spacing (smaller = more trees; 3m gives ~2M for 10km radius)
- 8m spacing = ~255k trees; 3m = ~2M+; 1m = ~10M (too many)

## Performance targets

- RTX 5070 Ti target — no quality compromises
- 200k buildings: ~40 Primitives, ~500ms CPU to build, draws fine at 60 FPS
- 2M trees: ~40 Primitives, ~10s CPU geometry build, ~1.5 GB GPU memory
- Terrain exaggeration 1.5x for "video game aesthetic"

## What NOT to do

- Don't use `vite-plugin-cesium` — copy assets manually to `public/cesium/`
- Don't use `Cesium.sampleTerrainMostDetailed` — doesn't work with `CustomHeightmapTerrainProvider`, silently returns 0
- Don't use raw `Cesium.Geometry` with manual `Cartesian3.normalize` — fails on degenerate polygons with "normalized result is not a number"
- Don't create individual `Cesium.Entity` per building or tree — way too slow at scale
- Don't forget to clear `data/output/scene_cache/` when changing binary format
- Don't put cache directory under `backend/` — it's at `data/output/` (project-relative)
