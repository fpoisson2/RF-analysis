"""Rebase building OBJs from MTM7 absolute coords to landscape-relative
coords so they can be imported into UE5 at the world origin with no
Actor offset needed.

For each input chunk_*.obj:
  - X' = X - origin_x_m                    (metres east of landscape NW)
  - Y' = origin_y_m - Y                    (metres south; UE Y+ = south)
  - Z' = Z                                 (unchanged metres)

Writes ``<out>/chunk_*_local.obj`` ready for UE import with
Build Scale = 100 (mΒ -> cm).

Usage:
    python scripts/rebase_obj_to_landscape.py \\
        --in data/unreal/buildings/tmp \\
        --out data/unreal/buildings/tmp_local
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir",
                    default="data/unreal/buildings/tmp")
    ap.add_argument("--out", default="data/unreal/buildings/tmp_local")
    ap.add_argument("--manifest",
                    default="data/unreal/heightmap/manifest_single.json")
    ap.add_argument("--unit-cm", action="store_true",
                    help="Output vertices in centimetres (x100) so UE import "
                         "can use Build Scale = 1.")
    ap.add_argument("--no-flip-y", action="store_true",
                    help="Don't flip Y (use if landscape +Y points north).")
    ap.add_argument("--size-m", type=float, default=12099.0,
                    help="Landscape size in metres (used for no-flip)")
    args = ap.parse_args()

    mf = json.loads((ROOT / args.manifest).read_text())
    ox = float(mf["origin_x_m"])
    oy = float(mf["origin_y_m"])
    print(f"[origin] MTM7 ({ox:.1f}, {oy:.1f})")

    in_dir = ROOT / args.in_dir
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    objs = sorted(in_dir.glob("chunk_*.obj"))
    print(f"[plan] {len(objs)} OBJ files to rebase")

    for i, src in enumerate(objs, 1):
        dst = out_dir / (src.stem + "_local.obj")
        with src.open(encoding="utf-8", errors="replace") as fi, \
             dst.open("w", encoding="utf-8") as fo:
            for line in fi:
                if line.startswith("v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            x = float(parts[1]); y = float(parts[2])
                            z = float(parts[3])
                        except ValueError:
                            fo.write(line); continue
                        xp = x - ox
                        if args.no_flip_y:
                            yp = y - (oy - args.size_m)
                        else:
                            yp = oy - y
                        zp = z
                        if args.unit_cm:
                            xp *= 100.0; yp *= 100.0; zp *= 100.0
                        fo.write(f"v {xp:.3f} {yp:.3f} {zp:.3f}\n")
                        continue
                fo.write(line)
        if i % 10 == 0 or i == len(objs):
            print(f"  [{i}/{len(objs)}] {src.name}")

    print(f"[done] -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
