"""Module 8 — Batch Real-ESRGAN x4 over a texture folder.

Thin wrapper around ``realesrgan-ncnn-vulkan`` (fastest for batch — uses
Vulkan, works on any modern GPU incl. RTX 5070 Ti), with resume support
and a manifest mapping original → upscaled paths.

Alternatively falls back to the Python ``realesrgan`` package if the ncnn
binary is not on PATH.

Usage:
    python scripts/upscale_textures_realesrgan.py \
        --in data/unreal/roof_textures --out data/unreal/roof_textures_4x

Expected to be run after ``project_roof_textures.py``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bin() -> str | None:
    for c in ("realesrgan-ncnn-vulkan", "realesrgan-ncnn-vulkan.exe"):
        p = shutil.which(c)
        if p: return p
    return None


def _py_fallback(inp: Path, out: Path, scale: int) -> bool:
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        import torch, numpy as np
        from PIL import Image
    except ImportError:
        return False
    print("[py ] using python realesrgan (slow; install realesrgan-ncnn-vulkan for speed)")
    model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23,
                    num_grow_ch=32, scale=scale)
    up = RealESRGANer(scale=scale, model_path=None, model=model,
                      tile=512, tile_pad=10, pre_pad=0, half=torch.cuda.is_available())
    for src in sorted(inp.rglob("*.png")):
        dst = out / src.relative_to(inp)
        if dst.exists(): continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        img = np.array(Image.open(src))
        out_img, _ = up.enhance(img, outscale=scale)
        Image.fromarray(out_img).save(dst)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="in_dir",  required=True)
    ap.add_argument("--out", dest="out_dir", required=True)
    ap.add_argument("--scale", type=int, default=4, choices=[2, 3, 4])
    ap.add_argument("--model", default="realesrgan-x4plus")
    args = ap.parse_args()

    inp = Path(args.in_dir); out = Path(args.out_dir)
    if not inp.exists():
        print(f"[err] {inp} missing", file=sys.stderr); return 2
    out.mkdir(parents=True, exist_ok=True)

    binpath = _bin()
    files = sorted([p for p in inp.rglob("*.png") if not p.name.startswith("_")])
    todo = [p for p in files if not (out / p.relative_to(inp)).exists()]
    print(f"[plan] {len(files)} pngs, {len(todo)} to upscale (x{args.scale})")

    manifest = {"scale": args.scale, "model": args.model, "files": []}
    if not binpath:
        ok = _py_fallback(inp, out, args.scale)
        if not ok:
            print("[err] no realesrgan backend. Install realesrgan-ncnn-vulkan "
                  "(https://github.com/xinntao/Real-ESRGAN/releases) or "
                  "`pip install realesrgan basicsr`", file=sys.stderr); return 2
    else:
        for p in todo:
            dst = out / p.relative_to(inp)
            dst.parent.mkdir(parents=True, exist_ok=True)
            cmd = [binpath, "-i", str(p), "-o", str(dst),
                   "-s", str(args.scale), "-n", args.model]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"[err] {p.name}: {r.stderr[:200]}", file=sys.stderr); continue

    for p in files:
        dst = out / p.relative_to(inp)
        if dst.exists():
            manifest["files"].append({"src": str(p.relative_to(inp)),
                                      "dst": str(dst.relative_to(out))})
    (out / "_manifest.json").write_text(json.dumps(manifest))
    print(f"[done] {len(manifest['files'])} upscaled → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
