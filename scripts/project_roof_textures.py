"""Module 3a — Project orthophoto pixels onto building rooftops.

For each building footprint, clips the overlapping orthophoto tile(s),
mosaics if the footprint spans multiple tiles, rotates to the footprint's
oriented minimum bounding box, and writes a PNG sized to the footprint
aspect ratio (max dimension = --max-px, default 1024).

Also writes ``_index.json`` mapping OBJECTID → roof image file + oriented
bbox dimensions (width_m, length_m, yaw_deg) so Unreal materials can map
the texture onto the extruded roof plane.

Skips buildings smaller than --min-area m² (default 40) to avoid garages
and doghouses eating disk space.

Usage:
    python scripts/project_roof_textures.py \
        --ortho E:/rf_analysis/ortho_tiles \
        --out data/unreal/roof_textures --max-px 1024
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLDG_GJSON = ROOT / "data" / "buildings" / "quebec_city_batiments.geojson"


def _min_rotated_rect(poly):
    """Return (cx, cy, width_m, length_m, yaw_deg) of the oriented bbox."""
    from shapely.geometry import Polygon
    mrr = poly.minimum_rotated_rectangle
    xs, ys = mrr.exterior.coords.xy
    pts = list(zip(xs[:-1], ys[:-1]))  # drop closing point
    edges = [(pts[i], pts[(i + 1) % 4]) for i in range(4)]
    edge_lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in edges]
    # longest edge
    i = edge_lens.index(max(edge_lens))
    a, b = edges[i]
    yaw = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    length = edge_lens[i]
    width = edge_lens[(i + 1) % 4]
    cx = sum(x for x, _ in pts) / 4
    cy = sum(y for _, y in pts) / 4
    return cx, cy, width, length, yaw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ortho", default="E:/rf_analysis/ortho_tiles")
    ap.add_argument("--out", default="data/unreal/roof_textures")
    ap.add_argument("--max-px", type=int, default=1024)
    ap.add_argument("--min-area", type=float, default=40.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    try:
        import geopandas as gpd
        import rasterio
        from rasterio.mask import mask as rio_mask
        from rasterio.merge import merge as rio_merge
        import numpy as np
        from PIL import Image
    except ImportError as e:
        print(f"Missing: {e}  (pip install geopandas rasterio pillow)",
              file=sys.stderr); return 2

    ortho_dir = Path(args.ortho)
    tifs = sorted(ortho_dir.glob("*.tif"))
    if not tifs:
        print(f"[err] no orthophotos in {ortho_dir}", file=sys.stderr); return 2

    # Tile index for quick bbox hits
    print(f"[idx] {len(tifs)} orthophoto tiles")
    tile_info = []
    for t in tifs:
        with rasterio.open(t) as s:
            tile_info.append({"path": t, "bounds": s.bounds, "crs": s.crs})
    tcrs = tile_info[0]["crs"]

    print(f"[load] {BLDG_GJSON.name}…")
    gdf = gpd.read_file(BLDG_GJSON).to_crs(tcrs)
    if "OBJECTID" not in gdf.columns:
        gdf = gdf.reset_index().rename(columns={"index": "OBJECTID"})
    gdf["_area"] = gdf.geometry.area
    gdf = gdf[gdf["_area"] >= args.min_area].reset_index(drop=True)
    print(f"[load] {len(gdf)} buildings ≥ {args.min_area} m²")

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    n_ok = n_skip = n_err = 0

    tot = args.limit or len(gdf)
    for i, row in gdf.head(tot).iterrows():
        oid = str(row["OBJECTID"])
        shard = oid[-2:].zfill(2)
        shard_dir = out_dir / shard
        shard_dir.mkdir(exist_ok=True)
        out_png = shard_dir / f"{oid}.png"
        if out_png.exists() and out_png.stat().st_size > 0:
            n_skip += 1; continue

        geom = row.geometry
        minx, miny, maxx, maxy = geom.bounds
        hits = [ti["path"] for ti in tile_info
                if not (ti["bounds"].right < minx or ti["bounds"].left > maxx or
                        ti["bounds"].top < miny or ti["bounds"].bottom > maxy)]
        if not hits:
            n_skip += 1; continue
        try:
            srcs = [rasterio.open(p) for p in hits]
            if len(srcs) == 1:
                img, tf = rio_mask(srcs[0], [geom], crop=True, filled=True,
                                   nodata=0, pad=False)
            else:
                mos, tf = rio_merge(srcs)
                # apply mask manually
                from rasterio.features import geometry_mask
                h, w = mos.shape[1], mos.shape[2]
                m = geometry_mask([geom], out_shape=(h, w), transform=tf,
                                  invert=True)
                img = mos * m
            for s in srcs: s.close()
        except Exception as e:
            n_err += 1
            if n_err < 5: print(f"[err] {oid}: {e}", file=sys.stderr)
            continue

        # RGB → max 3 bands
        if img.shape[0] > 3: img = img[:3]
        if img.shape[0] == 1: img = np.repeat(img, 3, axis=0)
        rgb = np.transpose(img, (1, 2, 0)).astype(np.uint8)

        # Resize to aspect of oriented bbox
        cx, cy, w_m, l_m, yaw = _min_rotated_rect(geom)
        long_side = max(w_m, l_m); short_side = min(w_m, l_m)
        aspect = short_side / long_side if long_side > 0 else 1.0
        out_w = args.max_px
        out_h = max(32, int(out_w * aspect))
        Image.fromarray(rgb).resize((out_w, out_h), Image.LANCZOS).save(out_png)

        index[oid] = {
            "file": f"{shard}/{oid}.png",
            "width_m": round(short_side, 2),
            "length_m": round(long_side, 2),
            "yaw_deg": round(yaw, 2),
            "centroid_x_m": round(cx, 2),
            "centroid_y_m": round(cy, 2),
        }
        n_ok += 1
        if n_ok % 500 == 0:
            print(f"[prog] {n_ok} roofs, {n_skip} skipped, {n_err} err")
            (out_dir / "_index.json").write_text(json.dumps(index))

    (out_dir / "_index.json").write_text(json.dumps(index))
    print(f"[done] ok={n_ok} skip={n_skip} err={n_err} → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
