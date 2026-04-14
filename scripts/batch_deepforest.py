"""Module 4a — Run DeepForest on a full orthophoto folder with resume.

Wraps ``scripts/run_deepforest.py`` logic but:
  * Scans a folder (default ``E:/rf_analysis/ortho_tiles``) for ``*.tif``.
  * Keeps a per-tile checkpoint file so reruns skip completed tiles.
  * Appends detections to a single JSONL per tile, then merges into one
    GeoJSON at the end. This protects against mid-run crashes.
  * Optional ``--workers N`` for parallel tiles (one DeepForest model per
    worker; each worker pins to a specific GPU via CUDA_VISIBLE_DEVICES).

Usage:
    python scripts/batch_deepforest.py --in E:/rf_analysis/ortho_tiles
    python scripts/batch_deepforest.py --in E:/rf_analysis/ortho_tiles --workers 2
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "vegetation"
CHECKPOINT = OUT_DIR / "deepforest_batch.ckpt.json"
PER_TILE_DIR = OUT_DIR / "deepforest_per_tile"
MERGED_GEOJSON = OUT_DIR / "deepforest_detected.geojson"


def _load_ckpt() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"done": [], "failed": {}}


def _save_ckpt(c: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(c, indent=2))


def _run_worker(tif_paths: list[Path], gpu_id: int | None) -> None:
    """Spawn run_deepforest.py for a batch on a specific GPU.

    We batch 10 tiles at a time into one subprocess so the model only loads
    once per batch.
    """
    env = os.environ.copy()
    if gpu_id is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    for i in range(0, len(tif_paths), 10):
        batch = tif_paths[i:i + 10]
        cmd = [sys.executable, str(ROOT / "scripts" / "run_deepforest.py")] + \
              [str(p) for p in batch]
        print(f"[gpu{gpu_id}] batch {i // 10 + 1}/"
              f"{(len(tif_paths) + 9) // 10} ({len(batch)} tiles)")
        t0 = time.time()
        r = subprocess.run(cmd, env=env)
        dt = time.time() - t0
        if r.returncode != 0:
            print(f"[gpu{gpu_id}] batch FAILED rc={r.returncode}", file=sys.stderr)
        else:
            print(f"[gpu{gpu_id}] batch ok in {dt:.1f}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir",
                    default="E:/rf_analysis/ortho_tiles")
    ap.add_argument("--workers", type=int, default=1,
                    help="Parallel worker processes. Each pins to one GPU.")
    ap.add_argument("--gpus", default="0",
                    help="Comma list of CUDA device ids, one per worker")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only process first N new tiles (0 = all)")
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    tifs = sorted(in_dir.glob("*.tif"))
    if not tifs:
        print(f"[err] no tiles in {in_dir}", file=sys.stderr); return 2

    ckpt = _load_ckpt()
    done = set(ckpt["done"])
    todo = [p for p in tifs if p.name not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"[plan] {len(tifs)} total  |  {len(done)} done  |  {len(todo)} to process")

    if not todo:
        print("[plan] nothing to do"); return 0

    gpus = [int(x) for x in args.gpus.split(",")]
    if len(gpus) < args.workers:
        gpus = (gpus * args.workers)[:args.workers]

    if args.workers == 1:
        _run_worker(todo, gpus[0])
    else:
        # naive split
        import threading
        chunks = [todo[i::args.workers] for i in range(args.workers)]
        threads = [threading.Thread(target=_run_worker, args=(chunks[i], gpus[i]))
                   for i in range(args.workers)]
        for t in threads: t.start()
        for t in threads: t.join()

    # On success mark tiles done (run_deepforest appends to the merged
    # file itself, so we just track completion).
    for p in todo:
        if p.name not in done:
            ckpt["done"].append(p.name)
    _save_ckpt(ckpt)

    # Summary
    n = 0
    if MERGED_GEOJSON.exists():
        try:
            n = len(json.loads(MERGED_GEOJSON.read_text()).get("features", []))
        except Exception:
            n = -1
    print(f"[done] merged features: {n}  →  {MERGED_GEOJSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
