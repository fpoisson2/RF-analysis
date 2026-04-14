"""Module 1 -- LiDAR MNT -> Unreal Landscape heightmap.

Reads the MNT GeoTIFFs in ``data/lidar/quebec_city/`` (1 m/px MRNF tiles,
EPSG:2949 NAD83 CSRS MTM7; already metric), limits to a user-provided
bbox, and writes tiled 16-bit PNGs sized for Unreal Engine 5 Landscape
import (recommended tile sizes: 1009, 2017, 4033, 8129 -- "2^n + 1").

Memory-safe: processes one Unreal tile at a time using windowed reads
from each MNT -- never materializes the full city as float32.

Usage (10 km around Vieux-Quebec, 2m/px, 4033-px tiles):
    python scripts/build_heightmap.py --center-lat 46.8139 --center-lon -71.2080 \\
        --km 10 --resolution 2.0 --tile-size 4033

Requires: rasterio, numpy, pyproj, pillow. Optional: scipy (nodata fill).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import gc
import os
import numpy as np

# Cap GDAL's raster block cache so it doesn't swell beyond the Python heap.
os.environ.setdefault("GDAL_CACHEMAX", "256")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

# Force UTF-8 on Windows (default cp1252 chokes on "->" arrows etc.)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
LIDAR_DIR = ROOT / "data" / "lidar" / "quebec_city"
NATIVE_CRS = "EPSG:2949"


def _gather_sources():
    paths = sorted(LIDAR_DIR.glob("MNT_*.tif"))
    if not paths:
        raise FileNotFoundError(f"No MNT_*.tif in {LIDAR_DIR}")
    return paths


def _center_to_native(lat: float, lon: float) -> tuple[float, float]:
    from pyproj import Transformer
    t = Transformer.from_crs(4326, 2949, always_xy=True)
    return t.transform(lon, lat)


def _scan_z_range(src_paths, bbox_native) -> tuple[float, float]:
    """Scan z min/max over the target bbox by reading each MNT tile's
    intersecting blocks at coarse resolution."""
    import rasterio
    from rasterio.windows import from_bounds, intersection
    lo, hi = math.inf, -math.inf
    for p in src_paths:
        with rasterio.open(p) as s:
            try:
                w_full = from_bounds(*bbox_native, transform=s.transform)
                w_src = rasterio.windows.Window(0, 0, s.width, s.height)
                w = intersection(w_full, w_src).round_offsets().round_lengths()
                if w.width <= 0 or w.height <= 0:
                    continue
            except Exception:
                continue
            # Decimated read -- 512 px is enough for z-range scanning
            arr = s.read(1, window=w, out_shape=(512, 512),
                         resampling=rasterio.enums.Resampling.nearest,
                         masked=True)
            if arr.size == 0:
                continue
            if arr.count() == 0:
                continue
            vmin = float(arr.min()); vmax = float(arr.max())
            if math.isfinite(vmin) and vmin < lo: lo = vmin
            if math.isfinite(vmax) and vmax > hi: hi = vmax
        gc.collect()
    return lo, hi


def _sample_tile(src_paths, x0, y0, size_px, res_m, z_min, z_max, fill):
    """Build one Unreal tile as uint16 by reading windowed data from
    any MNT that intersects its bbox. Sources are re-opened per tile
    so GDAL releases their block cache when the tile is done."""
    import rasterio
    from rasterio.windows import from_bounds

    xmax = x0 + size_px * res_m
    ymin = y0 - size_px * res_m  # y decreases going down (North-up)
    bbox = (x0, ymin, xmax, y0)
    out = np.full((size_px, size_px), np.nan, dtype=np.float32)
    for p in src_paths:
        with rasterio.open(p) as s:
            b = s.bounds
            if (b.right <= bbox[0] or b.left >= bbox[2] or
                b.top   <= bbox[1] or b.bottom >= bbox[3]):
                continue
            try:
                w = from_bounds(*bbox, transform=s.transform)
            except Exception:
                continue
            arr = s.read(
                1,
                out_shape=(size_px, size_px),
                window=w,
                resampling=rasterio.enums.Resampling.bilinear,
                masked=True,
            ).filled(np.nan).astype(np.float32)
        m = ~np.isnan(arr) & np.isnan(out)
        out[m] = arr[m]
        del arr, m
        gc.collect()
    nan_frac = np.isnan(out).mean()
    if fill and nan_frac > 0 and nan_frac < 1.0:
        try:
            from scipy.ndimage import distance_transform_edt
            mask = np.isnan(out)
            idx = distance_transform_edt(mask, return_distances=False,
                                         return_indices=True)
            out = out[tuple(idx)]
        except ImportError:
            pass
    # In-place ops to avoid 4x allocation peak
    nans = np.isnan(out)
    out[nans] = z_min
    out -= z_min
    out *= 65535.0 / max(z_max - z_min, 1e-6)
    np.clip(out, 0, 65535, out=out)
    u16 = out.astype(np.uint16)
    del out, nans
    gc.collect()
    return u16, nan_frac


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/unreal/heightmap")
    ap.add_argument("--tile-size", type=int, default=4033,
                    help="Unreal tile size in pixels (2^n + 1)")
    ap.add_argument("--resolution", type=float, default=2.0,
                    help="Metres per pixel (higher = smaller output)")
    ap.add_argument("--center-lat", type=float, default=46.8139)
    ap.add_argument("--center-lon", type=float, default=-71.2080)
    ap.add_argument("--km", type=float, default=10.0,
                    help="Half-size of square bbox in km (so total = 2*km)")
    ap.add_argument("--fill-nodata", action="store_true")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("Missing pillow: pip install pillow", file=sys.stderr); return 2

    cx, cy = _center_to_native(args.center_lat, args.center_lon)
    half = args.km * 1000.0
    bbox = (cx - half, cy - half, cx + half, cy + half)
    print(f"[bbox] center=({args.center_lat},{args.center_lon}) "
          f"-> native=({cx:.0f},{cy:.0f})  half={half:.0f} m")
    print(f"[bbox] {bbox}")

    srcs = _gather_sources()
    print(f"[src ] {len(srcs)} MNT tiles")

    # Snap bbox to integer multiples of resolution so Unreal tiles line up
    res = args.resolution
    x0_world = math.floor(bbox[0] / res) * res
    y_top_world = math.ceil(bbox[3] / res) * res
    # Total pixel size in world
    total_w_px = int(math.ceil((bbox[2] - x0_world) / res))
    total_h_px = int(math.ceil((y_top_world - bbox[1]) / res))
    step = args.tile_size - 1  # 1px overlap for Unreal World Composition
    nx = max(1, math.ceil(total_w_px / step))
    ny = max(1, math.ceil(total_h_px / step))
    print(f"[grid] {nx} x {ny} Unreal tiles of {args.tile_size} px @ {res} m/px "
          f"(step={step})")

    print(f"[scan] z range over bbox...")
    z_min, z_max = _scan_z_range(srcs, bbox)
    if not math.isfinite(z_min) or not math.isfinite(z_max) or z_max <= z_min:
        print(f"[err] bad z range: {z_min} -> {z_max}", file=sys.stderr)
        for s in srcs: s.close()
        return 3
    print(f"[scan] z = {z_min:.2f} -> {z_max:.2f} m  (delta={z_max - z_min:.2f})")

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "crs": NATIVE_CRS, "resolution_m": res,
        "tile_size_px": args.tile_size,
        "z_min": z_min, "z_max": z_max,
        "origin_x_m": x0_world, "origin_y_m": y_top_world,
        "grid_x": nx, "grid_y": ny,
        "tiles": [],
    }
    for ty in range(ny):
        for tx in range(nx):
            tile_x0 = x0_world + tx * step * res
            tile_y0 = y_top_world - ty * step * res
            u16, nan_frac = _sample_tile(
                srcs, tile_x0, tile_y0, args.tile_size,
                res, z_min, z_max, args.fill_nodata)
            name = f"heightmap_x{tx}_y{ty}.png"
            Image.fromarray(u16, mode="I;16").save(out_dir / name)
            manifest["tiles"].append({
                "file": name, "tx": tx, "ty": ty,
                "origin_x_m": tile_x0, "origin_y_m": tile_y0,
                "nan_frac": round(float(nan_frac), 4),
            })
            print(f"  [w] {name}  nan={nan_frac * 100:.1f}%")

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"[done] {nx * ny} tiles + manifest.json -> {out_dir}")
    print("\nUnreal import hint:")
    print("  Landscape Mode -> Manage -> Import from File -> select all PNGs")
    print(f"  X,Y scale: {res * 100:.1f} cm/px  "
          f"Z scale: choose so 65535 ~= {z_max - z_min:.1f} m "
          f"(Unreal z unit = 512 cm -> scale = {(z_max - z_min) * 100 / 512:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
