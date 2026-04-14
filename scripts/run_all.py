"""Run the full digital-twin pipeline end-to-end.

Steps (with rough runtimes on an RTX 5070 Ti + NVMe):
  1. download_data.py                  —  2 min  (small files)
  2. build_heightmap.py                — 10 min  (MNT mosaic + tiling)
  3. build_buildings_citygml.py        — 60 min  (3dfier over ~200k bldgs)
  4. batch_deepforest.py               — several hours for 1500 tiles
     (RUN THIS IN A SEPARATE TERMINAL — it's GPU-bound)
  5. merge_tree_catalog.py             —  5 min
  6. export_trees_unreal_pcg.py        —  1 min
  7. project_roof_textures.py          — 30–90 min for full city
  8. upscale_textures_realesrgan.py    — hours, GPU-bound
  9. fetch_mapillary.py                —  5–30 min (rate-limited)

Each step is idempotent / resumable. This orchestrator just runs them in
dependency order and stops on the first failure. Pass ``--skip-slow`` to
skip the two multi-hour steps (DeepForest and upscaling).

Usage:
    python scripts/run_all.py
    python scripts/run_all.py --skip-slow
    python scripts/run_all.py --only heightmap buildings
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

STEPS = [
    ("download",      "scripts/download_data.py",                  [], False),
    ("heightmap",     "scripts/build_heightmap.py",                [], False),
    ("buildings",     "scripts/build_buildings_citygml.py",        [], False),
    ("deepforest",    "scripts/batch_deepforest.py",               [], True),
    ("merge_trees",   "scripts/merge_tree_catalog.py",             [], False),
    ("export_trees",  "scripts/export_trees_unreal_pcg.py",        [], False),
    ("roof_textures", "scripts/project_roof_textures.py",          [], False),
    ("upscale",       "scripts/upscale_textures_realesrgan.py",
                      ["--in", "data/unreal/roof_textures",
                       "--out", "data/unreal/roof_textures_4x"],   True),
    ("mapillary",     "scripts/fetch_mapillary.py",                [], False),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-slow", action="store_true")
    ap.add_argument("--only", nargs="*", help="subset of step names to run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    only = set(args.only or [])
    failed = []
    for name, script, extra, slow in STEPS:
        if only and name not in only: continue
        if slow and args.skip_slow:
            print(f"[skip-slow] {name}"); continue
        cmd = [PY, str(ROOT / script)] + extra
        print(f"\n=== step: {name}  ({script}) ===")
        if args.dry_run:
            print("  $ " + " ".join(cmd)); continue
        t0 = time.time()
        r = subprocess.run(cmd)
        dt = time.time() - t0
        print(f"=== {name} finished in {dt:.1f}s (rc={r.returncode}) ===")
        if r.returncode != 0:
            failed.append(name)
            print(f"[stop] step {name} failed"); break
    if failed:
        print(f"\nFAILED: {failed}"); return 1
    print("\nAll requested steps completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
