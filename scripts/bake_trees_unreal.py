"""Bake tree positions from VdQ merged catalog into Unreal-ready world
coords aligned with the landscape at (0,0,0).

Input:  data/vegetation/trees_merged.csv (lon, lat, height_m, crown_m, species, ...)
Output: data/unreal/trees_ue/trees_ue.csv
        columns: mesh_group, x_cm, y_cm, z_cm, scale, yaw_deg, species

Filters: only trees whose UE position falls inside the landscape extent.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _slug(s: str) -> str:
    s = (s or "unknown").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "unknown"


_GENERA = {
    "acer": "maple",      "quercus": "oak",       "betula": "birch",
    "picea": "spruce",    "pinus": "pine",        "tilia": "linden",
    "fraxinus": "ash",    "ulmus": "elm",         "populus": "poplar",
    "salix": "willow",    "prunus": "cherry",     "malus": "apple",
    "thuja": "cedar",     "larix": "larch",       "abies": "fir",
    "fagus": "beech",     "juglans": "walnut",    "carya": "hickory",
}


def _mesh_group(species: str, height: float) -> str:
    sp_low = (species or "").lower()
    genus = "other"
    for g, name in _GENERA.items():
        if sp_low.startswith(g):
            genus = name; break
    bucket = "s" if height < 6 else "m" if height < 12 else "l" if height < 20 else "xl"
    return f"{genus}_{bucket}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in",  dest="in_csv",
                    default="data/vegetation/trees_merged.csv")
    ap.add_argument("--out", default="data/unreal/trees_ue/trees_ue.csv")
    ap.add_argument("--manifest",
                    default="data/unreal/heightmap/manifest_single.json")
    ap.add_argument("--heightmap",
                    default="data/unreal/heightmap/heightmap_single.png")
    ap.add_argument("--landscape-size-m", type=float, default=12099.0)
    ap.add_argument("--z-offset-cm", type=float, default=-5250.0)
    args = ap.parse_args()

    try:
        from pyproj import Transformer
    except ImportError:
        print("pip install pyproj", file=sys.stderr); return 2
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("pip install numpy pillow", file=sys.stderr); return 2

    mf = json.loads((ROOT / args.manifest).read_text())
    ox = float(mf["origin_x_m"])
    oy = float(mf["origin_y_m"])
    res_m = float(mf["resolution_m"])
    z_min = float(mf["z_min"])
    z_max = float(mf["z_max"])
    size_px = mf["size_px"]
    half_cm = args.landscape_size_m * 100.0 / 2.0
    print(f"[land] origin MTM7 ({ox:.1f}, {oy:.1f})  half={half_cm} cm")

    hm = np.array(Image.open(ROOT / args.heightmap))
    hm_h, hm_w = hm.shape[:2]
    print(f"[hm  ] {hm_w}x{hm_h} px, res={res_m} m/px, z=[{z_min:.1f},{z_max:.1f}]")

    def sample_z_m(mtm_x: float, mtm_y: float) -> float:
        """Bilinear sample of heightmap at MTM7 (x,y). rasterio writes
        PNG row 0 at the NORTH edge (tf.f). We flip UE Y below to align
        with that, so sampling uses the natural raster orientation.
        """
        px_x = (mtm_x - ox) / res_m
        px_y = (oy - mtm_y) / res_m
        if not (0 <= px_x < hm_w - 1 and 0 <= px_y < hm_h - 1):
            return 0.0
        x0 = int(px_x); y0 = int(px_y)
        fx = px_x - x0; fy = px_y - y0
        v00 = float(hm[y0,   x0])
        v10 = float(hm[y0,   x0 + 1])
        v01 = float(hm[y0+1, x0])
        v11 = float(hm[y0+1, x0 + 1])
        v = (v00 * (1-fx) * (1-fy) + v10 * fx * (1-fy)
             + v01 * (1-fx) * fy + v11 * fx * fy)
        return z_min + (v / 65535.0) * (z_max - z_min)

    # trees are in lat/lon (EPSG:4326). Convert to MTM7 (EPSG:2949).
    t = Transformer.from_crs(4326, 2949, always_xy=True)

    in_path = ROOT / args.in_csv
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_in = n_out = 0
    counts_by_group: dict[str, int] = {}

    with in_path.open(encoding="utf-8") as fi, \
         out_path.open("w", newline="", encoding="utf-8") as fo:
        r = csv.DictReader(fi)
        w = csv.writer(fo)
        w.writerow(["mesh_group", "x_cm", "y_cm", "z_cm",
                    "scale", "yaw_deg", "species", "height_m"])
        for row in r:
            n_in += 1
            try:
                lon = float(row["lon"]); lat = float(row["lat"])
                h = float(row["height_m"] or 8)
            except (KeyError, ValueError):
                continue
            mtm_x, mtm_y = t.transform(lon, lat)
            ux = (mtm_x - ox) * 100.0 - half_cm
            # UE Landscape PNG row 0 renders at min UE_Y; that PNG row 0
            # is MTM north in our raster. So MTM north must map to UE -Y.
            uy = (oy - mtm_y) * 100.0 - half_cm
            if not (-half_cm <= ux <= half_cm and -half_cm <= uy <= half_cm):
                continue
            # Sample ground elevation from heightmap PNG, then apply the
            # same UE Z formula used for buildings.
            ground_z_m = sample_z_m(mtm_x, mtm_y)
            uz = ground_z_m * 100.0 + args.z_offset_cm
            scale = max(0.3, h / 10.0)
            species = row.get("species") or ""
            yaw = int(hashlib.md5(f"{lon:.6f}_{lat:.6f}".encode())
                      .hexdigest()[:6], 16) % 360
            group = _mesh_group(species, h)
            w.writerow([group,
                        round(ux, 1), round(uy, 1), round(uz, 1),
                        round(scale, 3), yaw,
                        species, round(h, 1)])
            counts_by_group[group] = counts_by_group.get(group, 0) + 1
            n_out += 1

    print(f"[done] {n_out}/{n_in} trees inside landscape -> {out_path}")
    print("\nBy mesh group:")
    for g, c in sorted(counts_by_group.items(), key=lambda x: -x[1]):
        print(f"  {g:15s} {c:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
