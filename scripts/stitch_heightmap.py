"""Stitch the tiled heightmap PNGs into a single large PNG for UE5 import.

The tiles have 1-px overlap (Unreal World Composition convention). We
drop the shared overlap column/row so the final image is seamless.

Usage:
    python scripts/stitch_heightmap.py
    python scripts/stitch_heightmap.py --in data/unreal/heightmap \
        --out data/unreal/heightmap/heightmap_combined.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", default="data/unreal/heightmap")
    ap.add_argument("--out", default="data/unreal/heightmap/heightmap_combined.png")
    args = ap.parse_args()

    import numpy as np
    from PIL import Image

    in_dir = ROOT / args.in_dir
    manifest_path = in_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"[err] {manifest_path} missing", file=sys.stderr); return 2
    manifest = json.loads(manifest_path.read_text())

    tile_size = manifest["tile_size_px"]
    gx = manifest["grid_x"]; gy = manifest["grid_y"]
    overlap = 1
    step = tile_size - overlap
    final_w = gx * step + overlap
    final_h = gy * step + overlap
    print(f"[plan] grid {gx}x{gy} of {tile_size}px -> final {final_w}x{final_h}")

    out = np.zeros((final_h, final_w), dtype=np.uint16)
    for t in manifest["tiles"]:
        img = np.array(Image.open(in_dir / t["file"]))
        tx, ty = t["tx"], t["ty"]
        x0 = tx * step; y0 = ty * step
        out[y0:y0 + tile_size, x0:x0 + tile_size] = img
        print(f"  [w] {t['file']} at ({x0},{y0})")

    Image.fromarray(out, mode="I;16").save(ROOT / args.out)
    print(f"[done] {final_w}x{final_h} 16-bit PNG -> {args.out}")
    print(f"\nUE5 import:")
    print(f"  Landscape Mode -> Manage -> New -> Import from File")
    print(f"  Pick: {args.out}")
    print(f"  Scale: X=Y=200, Z={manifest['z_max'] - manifest['z_min']:.1f}*100/512"
          f" = {(manifest['z_max'] - manifest['z_min']) * 100 / 512:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
