"""Bake VdQ infrastructure GeoJSONs (roads, sidewalks, bike paths,
intersections) into UE-ready ribbon OBJs.

Reads 4 datasets in MTM7 (some may be WGS84 — auto-detected via the
`crs` field or first-coord magnitude), clips to the 12 km landscape
bbox, converts to UE world coords using the same formula as
bake_obj_unreal.py, samples terrain Z from the heightmap PNG, extrudes
each polyline into a 2-poly-wide ribbon with a configured width.

Output:  data/unreal/infra/<name>_ue.obj  (import at Build Scale 1,
         Actor Transform identity)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

# (name, source_path, width_m, z_offset_cm)
LAYERS = [
    ("roads",        "E:/rf_analysis/vdq_infra/roads.geojson",       7.0,   2.0),
    ("sidewalks",    "E:/rf_analysis/vdq_infra/pedestrian.geojson",  1.8,   12.0),
    ("cyclable",     "E:/rf_analysis/vdq_infra/cyclable.geojson",    1.5,   6.0),
]


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_heightmap(path: Path):
    from PIL import Image
    return np.array(Image.open(path))


def _iter_lines(gj: dict) -> Iterable[list[tuple[float, float]]]:
    for feat in gj.get("features", []):
        geom = feat.get("geometry") or {}
        t = geom.get("type")
        c = geom.get("coordinates", [])
        if t == "LineString":
            yield [(pt[0], pt[1]) for pt in c]
        elif t == "MultiLineString":
            for line in c:
                yield [(pt[0], pt[1]) for pt in line]


def _wgs84_to_mtm7(transformer, pts):
    return [transformer.transform(x, y) for x, y in pts]


def _needs_transform(first_xy):
    x, y = first_xy
    # MTM7 in Quebec ~ (244k..258k, 5.19M..5.2M). WGS84 ~ (-71.x, 46.x).
    return abs(x) < 200 and abs(y) < 100


def _perp(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = (dx * dx + dy * dy) ** 0.5
    if L < 1e-6:
        return 0.0, 0.0
    return -dy / L, dx / L


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest",
                    default="data/unreal/heightmap/manifest_single.json")
    ap.add_argument("--heightmap",
                    default="data/unreal/heightmap/heightmap_single.png")
    ap.add_argument("--out-dir", default="data/unreal/infra")
    ap.add_argument("--landscape-size-m", type=float, default=12099.0)
    ap.add_argument("--z-offset-cm", type=float, default=-5250.0)
    args = ap.parse_args()

    try:
        from pyproj import Transformer
    except ImportError:
        print("pip install pyproj pillow numpy", file=sys.stderr); return 2

    mf = _load_manifest(ROOT / args.manifest)
    ox = float(mf["origin_x_m"]); oy = float(mf["origin_y_m"])
    res_m = float(mf["resolution_m"])
    z_min = float(mf["z_min"]); z_max = float(mf["z_max"])
    size_px = mf["size_px"]
    half_cm = args.landscape_size_m * 100.0 / 2.0
    hm = _load_heightmap(ROOT / args.heightmap)
    hm_h, hm_w = hm.shape[:2]

    def sample_z_m(mx: float, my: float) -> float:
        px_x = (mx - ox) / res_m
        px_y = (oy - my) / res_m
        if not (0 <= px_x < hm_w - 1 and 0 <= px_y < hm_h - 1):
            return 0.0
        x0 = int(px_x); y0 = int(px_y)
        fx = px_x - x0; fy = px_y - y0
        v = (float(hm[y0,     x0]) * (1-fx) * (1-fy)
           + float(hm[y0,     x0 + 1]) * fx * (1-fy)
           + float(hm[y0 + 1, x0]) * (1-fx) * fy
           + float(hm[y0 + 1, x0 + 1]) * fx * fy)
        return z_min + (v / 65535.0) * (z_max - z_min)

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Reusable WGS84 -> MTM7 transformer
    to_mtm = Transformer.from_crs(4326, 2949, always_xy=True)

    for name, src_path, width_m, z_off in LAYERS:
        print(f"\n[{name}] loading {src_path}")
        gj = json.loads(Path(src_path).read_text(encoding="utf-8"))
        lines = list(_iter_lines(gj))
        print(f"[{name}] {len(lines)} lines")
        if not lines:
            continue

        # Detect CRS
        first_xy = lines[0][0]
        is_wgs84 = _needs_transform(first_xy)
        print(f"[{name}] CRS={'WGS84->MTM7' if is_wgs84 else 'MTM7 (native)'}")

        obj_path = out_dir / f"{name}_ue.obj"
        v_idx = 1
        n_kept = 0
        half_w = width_m / 2.0  # metres
        hw_cm = half_w * 100.0

        with obj_path.open("w") as fo:
            fo.write(f"# VdQ {name} as ribbons, width={width_m}m\n")
            fo.write(f"o {name}\n")
            for line in lines:
                # CRS convert if needed.
                pts = _wgs84_to_mtm7(to_mtm, line) if is_wgs84 else line
                # Clip: keep line if ANY point inside landscape bbox.
                any_inside = False
                ue_pts = []
                for (mx, my) in pts:
                    ux = (mx - ox) * 100.0 - half_cm
                    uy = (oy - my) * 100.0 - half_cm
                    if -half_cm <= ux <= half_cm and -half_cm <= uy <= half_cm:
                        any_inside = True
                    zm = sample_z_m(mx, my)
                    uz = zm * 100.0 + args.z_offset_cm + z_off
                    ue_pts.append((ux, uy, uz, mx, my))
                if not any_inside or len(ue_pts) < 2:
                    continue

                # Write ribbon verts (left/right of each node).
                base_v = v_idx
                for i, (ux, uy, uz, mx, my) in enumerate(ue_pts):
                    # Tangent direction from prev/next.
                    if i == 0:
                        nx, ny = ue_pts[1][0], ue_pts[1][1]
                        px = -(ny - uy); py = (nx - ux)
                    elif i == len(ue_pts) - 1:
                        nx, ny = ue_pts[i-1][0], ue_pts[i-1][1]
                        px = -(uy - ny); py = (ux - nx)
                    else:
                        ax, ay = ue_pts[i-1][0], ue_pts[i-1][1]
                        bx, by = ue_pts[i+1][0], ue_pts[i+1][1]
                        px = -(by - ay); py = (bx - ax)
                    L = (px*px + py*py) ** 0.5 or 1.0
                    px /= L; py /= L
                    lx = ux + px * hw_cm; ly = uy + py * hw_cm
                    rx = ux - px * hw_cm; ry = uy - py * hw_cm
                    fo.write(f"v {lx:.2f} {ly:.2f} {uz:.2f}\n")
                    fo.write(f"v {rx:.2f} {ry:.2f} {uz:.2f}\n")
                    v_idx += 2

                # Triangulate quad strip.
                for i in range(len(ue_pts) - 1):
                    l0 = base_v + 2*i;     r0 = l0 + 1
                    l1 = base_v + 2*(i+1); r1 = l1 + 1
                    fo.write(f"f {l0} {r0} {l1}\n")
                    fo.write(f"f {l1} {r0} {r1}\n")
                n_kept += 1

        print(f"[{name}] kept {n_kept} lines -> {obj_path}")

    print("\n[done] OBJs in", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
