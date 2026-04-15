# RF Coverage Analysis

Interactive 3D RF propagation tool for Quebec. Computes radio coverage and
point-to-point links over LiDAR-enhanced terrain, with a photorealistic
CesiumJS world (buildings + trees) and a Fresnel-zone aware path profile.

GPU-accelerated (CuPy + CUDA) with an automatic NumPy fallback. Backend in
Python/FastAPI, frontend in Vite + React + TypeScript + CesiumJS.

## Features

- **Coverage map** — colour raster around a transmitter, multiple propagation
  models, GPU-accelerated.
- **Point-to-point path profile** — bottom panel with terrain, canopy/buildings,
  line-of-sight, 1st Fresnel zone, signal level, obstruction list.
- **3D Fresnel ellipsoid** rendered around the TX↔RX axis on the globe.
- **Multiple receivers** — drop several RX, switch between them, see ITM and
  Fresnel-corrected RX signal in the sidebar list.
- **Hover readout** — GPS coords + signal/SNR/path-loss under the cursor.
- **Real LiDAR terrain** — MERN Québec MNT+MHC at 1 m resolution; ~285k
  building footprints; ~666k LiDAR-detected trees.
- **NTIA reference Longley-Rice (ITM)** via `pyitm` — same engine as Radio
  Mobile / SPLAT! — plus Hata, COST 231, SUI, Ericsson 9999, Egli, etc.
- **Bilingual UI** (FR/EN) with help tooltips on every parameter.

## Stack

| Layer       | Tech                                                          |
| ----------- | ------------------------------------------------------------- |
| Propagation | CuPy (CUDA 12.x), NumPy fallback, NTIA ITM (`pyitm`)          |
| Diffraction | Knife-edge, Bullington, Deygout-94                            |
| Terrain     | MERN Québec LiDAR 1 m (MNT + MHC), AWS Terrarium tiles        |
| Buildings   | Ville de Québec footprints (~285k)                            |
| Trees       | Detected from LiDAR canopy (~666k in 10 km radius)            |
| Backend     | FastAPI, rasterio, shapely, pyproj, opencv-headless           |
| Frontend    | Vite, React 18, TypeScript, Tailwind, CesiumJS                |

## Quick start

### Docker (recommended)

```bash
# CPU mode (any host):
docker compose up -d --build

# GPU mode (NVIDIA driver + nvidia-container-toolkit on host):
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Open <http://localhost:3000>. First boot takes ~90 s while the backend
indexes ~666k trees from the LiDAR.

### Bare-metal dev

Prerequisites: NVIDIA GPU (optional, for GPU mode), CUDA 12.x userspace,
LiDAR tiles in `data/lidar/quebec_city/`, buildings GeoJSON in
`data/buildings/`. See `DEPLOYMENT.md` for fetching data and configuring
the GPU.

```bash
# Backend (port 8000)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install opencv-python-headless           # tree detection
pip install cupy-cuda12x                     # optional: GPU acceleration
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Frontend (port 3000, proxies /api → 8000)
cd frontend
npm install
npm run dev
```

For a custom hostname behind a reverse proxy, add it to
`server.allowedHosts` in `frontend/vite.config.ts`.

## Project layout

```
backend/
  app/
    main.py                  # FastAPI app, endpoints, scene serialization
    coverage/engine.py       # GPU propagation engine, path profile
    terrain/lidar_terrain.py # LiDAR MNT/MHC reader (with swath sampling)
    propagation/
      models.py              # Free-space, Egli, Hata, COST 231, SUI, ITM…
      itm_ntia.py            # NTIA reference ITM (pyitm wrapper)
      diffraction.py         # Knife-edge, Bullington, Deygout-94
    vegetation/              # Tree detection from MHC
frontend/
  src/
    App.tsx                  # State, RX positions, path computation
    components/
      Map.tsx                # CesiumJS map + markers + path line
      Sidebar.tsx            # All RF parameters + RX list + help tooltips
      PathProfilePanel.tsx   # Bottom panel (SVG chart)
      HoverReadout.tsx       # Cursor signal readout
      cesium/
        TxMarker.ts          # Draggable transmitter marker
        RxMarker.ts          # Draggable receiver marker (one per RX)
        PathLine.ts          # 3D LoS + Fresnel ellipsoid + obstacle dots
        BuildingsMesh.ts     # 200k+ building extrusions
        TreesMesh.ts         # 666k+ tapered cones
        TerrainProvider.ts   # Custom Terrarium DEM provider
data/
  buildings/                 # Building footprints GeoJSON
  lidar/quebec_city/         # LiDAR MNT + MHC GeoTIFFs (~13 GB)
  output/
    scene_cache/             # Binary .sc3d per (lat, lon, radius)
    buildings_cache/         # Clipped buildings GeoJSON
    trees_cache/             # Detected trees
    dem_cache/               # Elevation DEMs
scripts/
  fetch_data.py              # Fetch buildings (GitHub Release or backup)
```

## Key API endpoints

| Path                                                 | Purpose                                            |
| ---------------------------------------------------- | -------------------------------------------------- |
| `GET  /api/health`                                   | Status, GPU/LiDAR availability                     |
| `GET  /api/data/scene?lat&lon&radius_km`             | Binary SC3D — buildings + trees                    |
| `POST /api/area`                                     | GPU coverage raster (image + bounds + stats)       |
| `GET  /api/coverage/tiles/{z}/{x}/{y}.png`           | Coverage raster as XYZ map tiles                   |
| `POST /api/coverage/sample`                          | Sample the cached coverage grid at a point         |
| `POST /api/path`                                     | Path profile — terrain, LoS, Fresnel, signal, obs. |
| `GET  /api/profile?lat1&lon1&lat2&lon2&points`       | Raw terrain profile (SRTM only)                    |
| `GET  /api/elevation?lat&lon`                        | Single-point elevation                             |
| `GET  /api/models`                                   | List propagation models                            |

## Path profile response (excerpt)

```jsonc
{
  "distances":         [0, 5, 10, …],          // m
  "ground_elevations": [12.1, 12.0, 11.8, …],  // MNT
  "surface_elevations":[12.1, 18.3, 21.0, …],  // MNT + MHC (canopy/buildings)
  "surface_detect":    [12.1, 19.7, 23.4, …],  // max within ±F1 perpendicular
  "los_line":          [42.1, 42.0, 41.9, …],  // tx→rx straight line
  "fresnel_radius":    [0, 1.2, 2.4, …],       // 1st Fresnel zone radius (m)
  "signal_levels":     [37, -2.1, -8.5, …],    // dBm with diffraction loss
  "fresnel_obstruction_pct": [0, 12.4, 38.0, …],// % zone area blocked
  "obstructions": [
    { "type": "los", "start_m": 720, "end_m": 768, "peak_m": 753,
      "peak_elevation": 23.4, "penetration_m": 2.7,
      "canopy_height": 7.6, "obstruction_pct": 100 },
    …
  ],
  "stats": {
    "distance_km": 3.06, "bearing_deg": 137.7,
    "tx_elevation": 8.1, "rx_elevation": 2.0,
    "signal_at_rx": -49.9, "signal_at_rx_itm": -45.6,
    "diffraction_loss": 4.3, "free_space_loss": 86.0,
    "n_los_obstructions": 6, "n_fresnel_obstructions": 8,
    "clear_path": false
  }
}
```

`signal_at_rx` includes the swath-aware diffraction loss; `signal_at_rx_itm`
is the propagation-model-only value (Longley-Rice without obstacle
diffraction). The two are shown side-by-side in the UI.

## Documentation

- `DEPLOYMENT.md` — Proxmox/LXC setup, NVIDIA passthrough, LiDAR fetch via
  SMB, troubleshooting checklist.
- `CLAUDE.md` — architecture notes and gotchas for contributors.
- `scripts/fetch_data.py` — buildings download helper.

## License

See `LICENSE` (add your own).
