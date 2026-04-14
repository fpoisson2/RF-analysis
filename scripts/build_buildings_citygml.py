"""Module 2 -- Footprints + MNT -> CityGML LOD1 + 3D Tiles.

Pipeline:
  1. Split ``data/buildings/quebec_city_batiments.geojson`` into N x N km
     chunks (3dfier is O(n log n) and memory-hungry; ~2 km chunks keep
     memory reasonable at Quebec's density).
  2. For each chunk, write a 3dfier YAML config referencing the local MNT
     tiles + the chunk's footprint subset, then invoke ``3dfier``.
  3. Merge per-chunk OBJ output into one 3D Tiles tileset via
     ``py3dtiles convert``.

3dfier can run natively (binary on PATH) OR via the official Docker image
(``tudelft3d/3dfier:latest``). The script auto-detects: if no native
binary, it falls back to Docker. Force a mode with ``--mode native|docker``.

Usage:
    python scripts/build_buildings_citygml.py --chunk-km 2 --out data/unreal/buildings
    python scripts/build_buildings_citygml.py --mode docker --skip-tiles
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
BLDG_GEOJSON = ROOT / "data" / "buildings" / "quebec_city_batiments.geojson"
MNT_DIR = ROOT / "data" / "lidar" / "quebec_city"
LAZ_DIR = Path("E:/rf_analysis/lidar_laz/tiles")
DOCKER_IMAGE = "tudelft3d/3dfier:latest"


def _chunks(gdf, chunk_m: float):
    import numpy as np
    gdf = gdf.to_crs(32618)
    minx, miny, maxx, maxy = gdf.total_bounds
    xs = np.arange(minx, maxx + chunk_m, chunk_m)
    ys = np.arange(miny, maxy + chunk_m, chunk_m)
    for ix in range(len(xs) - 1):
        for iy in range(len(ys) - 1):
            box = (xs[ix], ys[iy], xs[ix + 1], ys[iy + 1])
            sub = gdf.cx[box[0]:box[2], box[1]:box[3]]
            if len(sub) == 0:
                continue
            yield (ix, iy), box, sub


def _write_yaml(yaml_path: Path, footprint_path: str, laz_paths: list[str],
                uniqueid: str, has_class6: bool) -> None:
    """3dfier 1.4 YAML. Paths are already translated to container paths
    when using Docker.

    If ``has_class6`` is True, we assume proper classification and use
    class 6 for roofs, class 2 for ground (best quality).
    If not (MRNF Quebec raw data is 0,1,2,8 only), we use percentile-90
    of *all* above-ground points inside each footprint as roof proxy,
    and class 2+8 for ground.
    """
    roof_classes = "[6]" if has_class6 else "[0, 1]"
    ground_classes = "[2]" if has_class6 else "[2, 8]"
    lines = [
        "input_polygons:",
        "  - datasets:",
        f"      - {footprint_path}",
        f"    uniqueid: {uniqueid}",
        "    lifting: Building",
        "",
        "lifting_options:",
        "  Building:",
        "    roof:",
        "      height: percentile-90",
        f"      use_LAS_classes: {roof_classes}",
        "    ground:",
        "      height: percentile-10",
        f"      use_LAS_classes: {ground_classes}",
        "    lod: 1",
        "",
        "input_elevation:",
        "  - datasets:",
    ] + [f"      - {p}" for p in laz_paths] + [
        "    omit_LAS_classes:",
        "    thinning: 0",
        "",
        "options:",
        "  building_radius_vertex_elevation: 3.0",
        "  radius_vertex_elevation: 2.0",
        "  threshold_jump_edges: 0.5",
        "  stitching: true",
    ]
    yaml_path.write_text("\n".join(lines), encoding="utf-8")


def _native_available() -> bool:
    return shutil.which("3dfier") is not None


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE],
                           capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


def _laz_tiles_for_bbox(laz_paths: list[Path], bbox_32618, pad_m: float) -> list[Path]:
    """Return LAZ tiles whose name-derived bbox intersects the chunk bbox.

    MRNF tile names encode MTM coordinates, but since parsing that is brittle,
    we fall back to opening each LAZ header lazily with laspy to get bounds
    -- cached on first call.
    """
    try:
        import laspy
    except ImportError:
        return laz_paths  # fall back to using all tiles
    cache_attr = "_bounds_cache"
    if not hasattr(_laz_tiles_for_bbox, cache_attr):
        setattr(_laz_tiles_for_bbox, cache_attr, {})
    cache = getattr(_laz_tiles_for_bbox, cache_attr)
    # Transform bbox from EPSG:32618 (internal chunk CRS) to the LAZ CRS.
    # MRNF rows are in MTM7 (EPSG:2949) or MTM8/9 depending on project.
    # Simplest robust approach: project bbox to WGS84, then to each tile's CRS
    # separately via laspy when needed. Here we instead compare in 32618
    # after caching each tile's bounds in 32618.
    from pyproj import Transformer, CRS
    hits = []
    xl, yl, xr, yr = bbox_32618
    xl -= pad_m; yl -= pad_m; xr += pad_m; yr += pad_m
    for p in laz_paths:
        if p in cache:
            tb = cache[p]
        else:
            try:
                with laspy.open(p) as f:
                    hdr = f.header
                    src_crs = None
                    # Try to detect CRS via VLR; else assume MTM7 (EPSG:2949)
                    if hasattr(hdr, "parse_crs"):
                        try: src_crs = hdr.parse_crs()
                        except Exception: src_crs = None
                    if src_crs is None:
                        src_crs = CRS.from_epsg(2949)
                    tf = Transformer.from_crs(src_crs, 32618, always_xy=True)
                    x1, y1 = tf.transform(hdr.mins[0], hdr.mins[1])
                    x2, y2 = tf.transform(hdr.maxs[0], hdr.maxs[1])
                    tb = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            except Exception:
                tb = None
            cache[p] = tb
        if tb is None: continue
        if tb[2] < xl or tb[0] > xr or tb[3] < yl or tb[1] > yr:
            continue
        hits.append(p)
    return hits


def _to_container_path(p: Path, mount_host: Path, mount_container: str) -> str:
    """Translate a host-side Path to a container-side POSIX path.
    The host directory ``mount_host`` is bind-mounted at ``mount_container``."""
    rel = Path(p).resolve().relative_to(mount_host.resolve())
    return (mount_container + "/" + rel.as_posix()).replace("//", "/")


def _run_3dfier_native(yaml_path: Path, obj_path: Path) -> int:
    cmd = ["3dfier", str(yaml_path), "--OBJ", str(obj_path)]
    return subprocess.run(cmd).returncode


def _run_3dfier_docker(yaml_host: Path, obj_host: Path, mount_host: Path) -> int:
    yaml_c = _to_container_path(yaml_host, mount_host, "/data")
    obj_c = _to_container_path(obj_host, mount_host, "/data")
    host_path = str(mount_host.resolve()).replace("\\", "/")
    cmd = ["docker", "run", "--rm",
           "-v", f"{host_path}:/data",
           DOCKER_IMAGE,
           "3dfier", yaml_c, "--OBJ", obj_c]
    env = os.environ.copy()
    env["MSYS_NO_PATHCONV"] = "1"  # prevent MSYS from rewriting /data
    return subprocess.run(cmd, env=env).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk-km", type=float, default=2.0)
    ap.add_argument("--out", default="data/unreal/buildings")
    ap.add_argument("--mode", choices=["auto", "native", "docker"], default="auto")
    ap.add_argument("--mount-root", default=".",
                    help="Host path to bind-mount as /data inside Docker. "
                         "Must contain the footprint GeoJSON + MNT GeoTIFFs.")
    ap.add_argument("--skip-3dfier", action="store_true")
    ap.add_argument("--skip-tiles", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only process first N chunks (0 = all)")
    ap.add_argument("--laz-padding", type=float, default=20.0,
                    help="Metres to pad chunk bbox when selecting LAZ tiles")
    ap.add_argument("--has-class6", action="store_true",
                    help="LAZ tiles are classified with class 6 (buildings). "
                         "Default assumes MRNF raw data (classes 0,1,2,8).")
    args = ap.parse_args()

    if not BLDG_GEOJSON.exists():
        print(f"[err] missing {BLDG_GEOJSON}", file=sys.stderr); return 2
    laz_files = sorted(LAZ_DIR.glob("*.LAZ")) + sorted(LAZ_DIR.glob("*.laz"))
    if not laz_files:
        print(f"[err] no LAZ tiles in {LAZ_DIR}. "
              "Run scripts/download_lidar_laz.py first.", file=sys.stderr)
        return 2
    print(f"[laz ] {len(laz_files)} LAZ tiles")

    # Choose runner
    mode = args.mode
    if mode == "auto":
        if _native_available(): mode = "native"
        elif _docker_available(): mode = "docker"
        else:
            print("[err] neither native 3dfier nor Docker image "
                  f"{DOCKER_IMAGE} is available.", file=sys.stderr); return 2
    print(f"[mode] {mode}")

    mount_host = Path(args.mount_root).resolve()
    if mode == "docker":
        # Sanity: per-chunk GeoJSONs, LAZ tiles, and OBJ output live inside
        # mount_host; the root GeoJSON is read client-side so it's OK if
        # that one is on a different drive.
        for p in [LAZ_DIR.resolve(), (ROOT / args.out).resolve()]:
            try:
                p.relative_to(mount_host.resolve())
            except ValueError:
                print(f"[err] {p} is not under mount-root {mount_host}; "
                      f"Docker won't see it.", file=sys.stderr); return 2

    import geopandas as gpd
    out_dir = ROOT / args.out
    tmp_dir = out_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print(f"[load] {BLDG_GEOJSON.name}...")
    gdf = gpd.read_file(BLDG_GEOJSON)
    if "OBJECTID" not in gdf.columns:
        if "id" in gdf.columns: gdf = gdf.rename(columns={"id": "OBJECTID"})
        else: gdf = gdf.reset_index().rename(columns={"index": "OBJECTID"})
    gdf["OBJECTID"] = gdf["OBJECTID"].astype(str)
    print(f"[load] {len(gdf)} footprints")

    chunk_m = args.chunk_km * 1000.0
    objs: list[Path] = []
    count = 0
    for (ix, iy), bbox, sub in _chunks(gdf, chunk_m):
        chunk_name = f"chunk_x{ix}_y{iy}"
        fp = tmp_dir / f"{chunk_name}.geojson"
        obj = tmp_dir / f"{chunk_name}.obj"
        yaml = tmp_dir / f"{chunk_name}.yml"
        if obj.exists() and obj.stat().st_size > 0:
            print(f"[skip] {chunk_name}.obj"); objs.append(obj); continue
        sub.to_crs(2949).to_file(fp, driver="GeoJSON")  # match MNT CRS

        # Select only LAZ tiles that intersect this chunk's bbox to avoid
        # 3dfier opening 800+ tiles per chunk.
        chunk_laz = _laz_tiles_for_bbox(laz_files, bbox, args.laz_padding)
        if not chunk_laz:
            print(f"[skip] {chunk_name}: no LAZ tiles cover bbox"); continue
        if mode == "docker":
            fp_c   = _to_container_path(fp,     mount_host, "/data")
            laz_c  = [_to_container_path(m, mount_host, "/data") for m in chunk_laz]
        else:
            fp_c   = str(fp.resolve())
            laz_c  = [str(m.resolve()) for m in chunk_laz]
        _write_yaml(yaml, fp_c, laz_c, "OBJECTID", has_class6=args.has_class6)

        if args.skip_3dfier:
            objs.append(obj); continue
        print(f"[run ] {chunk_name} ({len(sub)} bldgs)")
        rc = (_run_3dfier_docker(yaml, obj, mount_host) if mode == "docker"
              else _run_3dfier_native(yaml, obj))
        if rc != 0 or not obj.exists():
            print(f"  [fail] rc={rc}", file=sys.stderr); continue
        objs.append(obj)
        count += 1
        if args.limit and count >= args.limit:
            break

    print(f"[ok]  {len(objs)} chunks produced")

    if args.skip_tiles or not objs:
        return 0
    try:
        import py3dtiles  # noqa: F401
    except ImportError:
        print("[warn] py3dtiles not installed (`pip install py3dtiles`)",
              file=sys.stderr); return 0

    tileset_dir = out_dir / "tileset"
    tileset_dir.mkdir(exist_ok=True)
    cmd = ["py3dtiles", "convert",
           "--out", str(tileset_dir), "--overwrite",
           "--srs-in", "2949", "--srs-out", "4978"] + [str(p) for p in objs]
    print(f"[run ] py3dtiles convert ({len(objs)} objs) ...")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("[warn] py3dtiles convert returned non-zero", file=sys.stderr)

    (out_dir / "manifest.json").write_text(json.dumps({
        "mode": mode,
        "chunks": [p.name for p in objs],
        "tileset": "tileset/tileset.json",
        "footprint_crs": "EPSG:2949",
    }, indent=2))
    print(f"[done] -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
