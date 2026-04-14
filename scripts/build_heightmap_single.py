"""Generate a single seamless 16-bit heightmap PNG over a bbox by merging
the MNT GeoTIFFs into one memory buffer with rasterio.merge (no tile-by-
tile interpolation = no seams).

Output: one PNG at the target --resolution spanning the bbox.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ.setdefault("GDAL_CACHEMAX", "1024")

ROOT = Path(__file__).resolve().parents[1]
LIDAR_DIR = ROOT / "data" / "lidar" / "quebec_city"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/unreal/heightmap/heightmap_single.png")
    ap.add_argument("--manifest",
                    default="data/unreal/heightmap/manifest_single.json")
    ap.add_argument("--center-lat", type=float, default=46.8139)
    ap.add_argument("--center-lon", type=float, default=-71.2080)
    ap.add_argument("--km", type=float, default=10.0)
    ap.add_argument("--resolution", type=float, default=2.0)
    args = ap.parse_args()

    from PIL import Image
    import rasterio
    from rasterio.merge import merge
    from pyproj import Transformer

    t = Transformer.from_crs(4326, 2949, always_xy=True)
    cx, cy = t.transform(args.center_lon, args.center_lat)
    half = args.km * 1000.0
    bbox = (cx - half, cy - half, cx + half, cy + half)
    print(f"[bbox] center=({args.center_lat},{args.center_lon}) "
          f"half={half:.0f}m  bbox={bbox}")

    srcs = [rasterio.open(p) for p in sorted(LIDAR_DIR.glob("MNT_*.tif"))]
    if not srcs:
        print("[err] no MNT tiles", file=sys.stderr); return 2
    print(f"[src] {len(srcs)} MNT tiles")

    # Merge -> single seamless array clipped to bbox at target resolution
    print(f"[merge] at {args.resolution} m/px over bbox...")
    arr, tf = merge(srcs, bounds=bbox,
                    res=(args.resolution, args.resolution),
                    resampling=rasterio.enums.Resampling.bilinear,
                    nodata=srcs[0].nodata,
                    target_aligned_pixels=True)
    for s in srcs: s.close()
    arr = arr[0].astype(np.float32)
    nd = srcs[0].nodata
    if nd is not None:
        arr = np.where(arr == nd, np.nan, arr)
    h, w = arr.shape
    print(f"[merge] shape={arr.shape} nan%={np.isnan(arr).mean() * 100:.2f}")

    # Fill NaN via nearest-neighbour distance transform (seamless)
    if np.isnan(arr).any():
        try:
            from scipy.ndimage import distance_transform_edt
            mask = np.isnan(arr)
            idx = distance_transform_edt(mask, return_distances=False,
                                         return_indices=True)
            arr = arr[tuple(idx)]
            print("[fill] nodata filled via EDT")
        except ImportError:
            arr = np.nan_to_num(arr, nan=float(np.nanmin(arr)))

    z_min = float(arr.min()); z_max = float(arr.max())
    print(f"[z   ] {z_min:.2f} -> {z_max:.2f} m")

    arr -= z_min
    arr *= 65535.0 / max(z_max - z_min, 1e-6)
    np.clip(arr, 0, 65535, out=arr)
    u16 = arr.astype(np.uint16)
    del arr; gc.collect()

    # UE5 expects "2^n + 1". Pick the largest valid size <= min(w, h)
    # and CENTER-CROP (no edge repetition).
    valid = (1009, 2017, 4033, 8129, 16257)
    target = max((v for v in valid if v <= min(w, h)), default=valid[0])
    if target != w or target != h:
        y0 = (h - target) // 2; x0 = (w - target) // 2
        print(f"[crop] {w}x{h} -> {target}x{target} "
              f"(crop at x0={x0} y0={y0})")
        u16 = u16[y0:y0 + target, x0:x0 + target]

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(u16, mode="I;16").save(out_path)

    manifest = {
        "crs": "EPSG:2949",
        "resolution_m": args.resolution,
        "z_min": z_min, "z_max": z_max,
        "origin_x_m": tf.c,
        "origin_y_m": tf.f,
        "size_px": [target, target],
        "original_size_px": [w, h],
        "ue_scale_xy": args.resolution * 100,
        "ue_scale_z": round((z_max - z_min) * 100 / 512, 4),
    }
    (ROOT / args.manifest).write_text(json.dumps(manifest, indent=2))
    print(f"[done] {target}x{target} 16-bit PNG -> {out_path}")
    print(f"\nUE5: Landscape -> New -> Import from File")
    print(f"  Pick: {out_path}")
    print(f"  Scale: X=Y={manifest['ue_scale_xy']}, Z={manifest['ue_scale_z']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
