"""Convert LAZ 1.4 / PointFormat 6+ files to LAZ 1.2 / PointFormat 3 so
3dfier (2020 Docker image) can read them.

Uses PDAL Docker image (``pdal/pdal``) to run ``pdal translate`` in
parallel over the LAZ tile folder. Source files are left in place; the
converted ones go to ``--out``.

Usage:
    python scripts/convert_laz_to_1_2.py \\
        --in E:/rf_analysis/lidar_laz/tiles \\
        --out E:/rf_analysis/lidar_laz/tiles_12 --workers 4

Then rerun the 3dfier pipeline with LAZ_DIR pointing at ``tiles_12``.
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

PDAL_IMAGE = "pdal/pdal:latest"


def _convert_one(src: Path, dst_dir: Path, mount_host: Path) -> tuple[str, int, float]:
    dst = dst_dir / src.name
    if dst.exists() and dst.stat().st_size > 1_000_000:
        return (src.name, 1, 0.0)
    src_c = "/data/" + src.resolve().relative_to(mount_host.resolve()).as_posix()
    dst_c = "/data/" + dst.resolve().relative_to(mount_host.resolve()).as_posix()
    host_path = str(mount_host.resolve()).replace("\\", "/")
    cmd = ["docker", "run", "--rm",
           "-v", f"{host_path}:/data",
           PDAL_IMAGE,
           "pdal", "translate", src_c, dst_c,
           "--writers.las.minor_version=2",
           "--writers.las.dataformat_id=3",
           "--writers.las.forward=all"]
    env = os.environ.copy(); env["MSYS_NO_PATHCONV"] = "1"
    t0 = time.time()
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    dt = time.time() - t0
    if r.returncode != 0 or not dst.exists():
        sys.stderr.write(f"[fail] {src.name} rc={r.returncode}  "
                         f"{r.stderr[-300:]}\n")
        try:
            if dst.exists() and dst.stat().st_size < 1_000_000:
                dst.unlink()
        except Exception: pass
        return (src.name, 2, dt)
    return (src.name, 0, dt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mount-root", default="E:/rf_analysis")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    in_dir = Path(args.in_dir); out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    mount_host = Path(args.mount_root)

    lazs = sorted(in_dir.glob("*.LAZ")) + sorted(in_dir.glob("*.laz"))
    if not lazs:
        print(f"[err] no LAZ in {in_dir}", file=sys.stderr); return 2
    todo = [p for p in lazs
            if not ((out_dir / p.name).exists() and
                    (out_dir / p.name).stat().st_size > 1_000_000)]
    print(f"[plan] {len(lazs)} LAZ total  |  "
          f"{len(lazs) - len(todo)} already done  |  "
          f"{len(todo)} to convert with {args.workers} workers")

    ok = skip = fail = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_convert_one, p, out_dir, mount_host): p for p in todo}
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            name, status, dt = fut.result()
            if status == 0: ok += 1; tag = "ok  "
            elif status == 1: skip += 1; tag = "skip"
            else: fail += 1; tag = "FAIL"
            elapsed = time.time() - t0
            eta = (len(todo) - i) / max(i / max(elapsed, 1e-6), 1e-6) / 60
            print(f"[{tag}] {i:>4}/{len(todo)}  {name:30s}  "
                  f"{dt:>5.1f}s  eta {eta:.0f} min")
    print(f"[done] ok={ok} skip={skip} fail={fail}  "
          f"wall={(time.time() - t0) / 60:.1f} min")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
