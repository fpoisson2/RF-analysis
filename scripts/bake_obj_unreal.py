"""Bake building OBJs into Unreal-ready world coords.

Output OBJs: import into UE5 with Build Scale = 1, drag into scene at
Translation = (0, 0, 0) and Scale = (1, 1, 1). Buildings will land
exactly on the landscape.

Formula (empirical, matches the working user setup):
  UE X = (X_mtm - origin_x_m) * 100  - LANDSCAPE_HALF_CM
  UE Y = (Y_mtm - origin_y_m) * 100  + LANDSCAPE_HALF_CM
  UE Z =  Z_mtm * 100               + Z_OFFSET_CM

Assumes the landscape actor is placed at (-HALF, -HALF, 0) with Scale
(300, 300, 32.75) and its heightmap orients +Y = North in world space.
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
    ap.add_argument("--out", default="data/unreal/buildings/tmp_baked")
    ap.add_argument("--manifest",
                    default="data/unreal/heightmap/manifest_single.json")
    ap.add_argument("--landscape-size-m", type=float, default=12099.0)
    ap.add_argument("--z-offset-cm", type=float, default=-5250.0,
                    help="Empirical Z shift. Default from user's working "
                         "config.")
    args = ap.parse_args()

    mf = json.loads((ROOT / args.manifest).read_text())
    ox = float(mf["origin_x_m"])
    oy = float(mf["origin_y_m"])
    half_cm = args.landscape_size_m * 100.0 / 2.0
    print(f"[origin] MTM7 ({ox:.1f}, {oy:.1f})")
    print(f"[land] size={args.landscape_size_m} m  half={half_cm} cm")
    print(f"[z   ] offset={args.z_offset_cm} cm")

    in_dir = ROOT / args.in_dir
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    objs = sorted(in_dir.glob("chunk_*.obj"))
    if not objs:
        print(f"[err] no OBJs in {in_dir}", file=sys.stderr); return 2
    print(f"[plan] {len(objs)} OBJs -> baked UE coords")

    for i, src in enumerate(objs, 1):
        dst = out_dir / (src.stem + "_ue.obj")
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
                        ux = (x - ox) * 100.0 - half_cm
                        uy = (y - oy) * 100.0 + half_cm
                        uz = z * 100.0 + args.z_offset_cm
                        fo.write(f"v {ux:.3f} {uy:.3f} {uz:.3f}\n")
                        continue
                fo.write(line)
        if i % 10 == 0 or i == len(objs):
            print(f"  [{i}/{len(objs)}] {src.name}")

    # Save a place-at-origin manifest for reference
    out_mf = {
        "import_build_scale": [1.0, 1.0, 1.0],
        "actor_translation_cm": [0.0, 0.0, 0.0],
        "actor_scale": [1.0, 1.0, 1.0],
        "landscape_translation_cm": [-half_cm, -half_cm, 0.0],
        "landscape_scale": [300.0, 300.0, 32.75],
    }
    (out_dir / "_import_config.json").write_text(json.dumps(out_mf, indent=2))

    print(f"[done] -> {out_dir}")
    print("\nUE5 import:")
    print("  Build Scale = 1,1,1. Combine Meshes = on. Nanite = on.")
    print("  Drag -> Translation (0,0,0), Scale (1,1,1), Rotation (0,0,0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
