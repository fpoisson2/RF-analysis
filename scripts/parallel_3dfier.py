"""Run 3dfier (Docker) on every pre-generated chunk YAML in parallel.

Assumes ``build_buildings_citygml.py`` has been run at least once so that
``data/unreal/buildings/tmp/chunk_*.yml`` + ``chunk_*.geojson`` exist
(it writes them before invoking 3dfier). This script skips the Python
footprint splitting entirely and just fans out the 3dfier invocation
to N concurrent Docker containers.

Usage:
    python scripts/parallel_3dfier.py --workers 4 \\
        --mount-root E:/rf_analysis

Resumes cleanly: chunks whose ``.obj`` already exists are skipped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "data" / "unreal" / "buildings" / "tmp"
DOCKER_IMAGE = "tudelft3d/3dfier:latest"


def _to_container_path(host: Path, mount_host: Path) -> str:
    rel = host.resolve().relative_to(mount_host.resolve())
    return "/data/" + rel.as_posix()


def _worker(yaml_path: Path, mount_host: Path) -> tuple[str, int, float]:
    obj_path = yaml_path.with_suffix(".obj")
    if obj_path.exists() and obj_path.stat().st_size > 0:
        return (yaml_path.stem, 1, 0.0)  # skip
    yaml_c = _to_container_path(yaml_path, mount_host)
    obj_c = _to_container_path(obj_path, mount_host)
    host_path = str(mount_host.resolve()).replace("\\", "/")
    cmd = ["docker", "run", "--rm",
           "-v", f"{host_path}:/data",
           DOCKER_IMAGE,
           "3dfier", yaml_c, "--OBJ", obj_c]
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"
    t0 = time.time()
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = time.time() - t0
    if r.returncode != 0 or not obj_path.exists():
        sys.stderr.write(f"[fail] {yaml_path.stem} rc={r.returncode}\n"
                         f"{r.stderr[-500:]}\n")
        return (yaml_path.stem, 2, dt)
    return (yaml_path.stem, 0, dt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--mount-root", default="E:/rf_analysis")
    ap.add_argument("--tmp", default=str(TMP_DIR))
    args = ap.parse_args()

    tmp_dir = Path(args.tmp)
    yamls = sorted(tmp_dir.glob("chunk_*.yml"))
    if not yamls:
        print(f"[err] no chunk_*.yml in {tmp_dir}. Run build_buildings_citygml.py "
              "first to generate them.", file=sys.stderr); return 2

    mount_host = Path(args.mount_root)
    todo = [y for y in yamls
            if not (y.with_suffix(".obj").exists()
                    and y.with_suffix(".obj").stat().st_size > 0)]
    print(f"[plan] {len(yamls)} yml total  |  "
          f"{len(yamls) - len(todo)} already done  |  "
          f"{len(todo)} to process with {args.workers} workers")

    ok = skip = fail = 0
    total_dt = 0.0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_worker, y, mount_host): y for y in todo}
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            name, status, dt = fut.result()
            total_dt += dt
            if status == 0: ok += 1; tag = "ok  "
            elif status == 1: skip += 1; tag = "skip"
            else: fail += 1; tag = "FAIL"
            elapsed = time.time() - t0
            rate = i / max(elapsed, 1e-6)
            eta_min = (len(todo) - i) / max(rate, 1e-6) / 60
            print(f"[{tag}] {i:>4}/{len(todo)}  {name:30s}  "
                  f"{dt:>5.1f}s  eta {eta_min:.0f} min")

    print(f"[done] ok={ok} skip={skip} fail={fail}  "
          f"wall={(time.time() - t0) / 60:.1f} min  "
          f"cpu={total_dt / 60:.1f} min")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
