"""Triangulate building height data across sources.

Joins:
  * VdQ footprints          (285k, no height)
  * RNCan auto-building     (245k, heightmin/heightmax, elevmin/elevmax)
  * MHC raster              (max canopy height over footprint, m)
  * 3dfier OBJ chunks       (when available)

Produces:
  * ``data/unreal/audit/heights_comparison.csv`` - per-building comparison
  * ``data/unreal/audit/heights_stats.json``     - global aggregates
  * Console histogram per source and source-vs-source deltas

Usage:
    python scripts/audit_building_heights.py
    python scripts/audit_building_heights.py --sample 10000   (faster subset)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
VDQ_GJSON = Path("E:/rf_analysis/data_backup/buildings_vdq/vdq-batiments.geojson")
RNCAN_DIR = Path("E:/rf_analysis/data_backup/buildings_rncan")
MHC_DIR = ROOT / "data" / "lidar" / "quebec_city"
TDFIER_TMP = ROOT / "data" / "unreal" / "buildings" / "tmp"
OUT_DIR = ROOT / "data" / "unreal" / "audit"


def _mhc_sample_max(geom, mhc_paths):
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.features import geometry_mask
    mx = -np.inf
    minx, miny, maxx, maxy = geom.bounds
    for p in mhc_paths:
        with rasterio.open(p) as s:
            b = s.bounds
            if b.right <= minx or b.left >= maxx or \
               b.top <= miny or b.bottom >= maxy:
                continue
            try:
                w = from_bounds(minx, miny, maxx, maxy,
                                transform=s.transform).round_offsets().round_lengths()
                if w.width <= 0 or w.height <= 0: continue
            except Exception:
                continue
            arr = s.read(1, window=w, masked=True)
            if arr.count() == 0: continue
            mask = geometry_mask([geom], out_shape=arr.shape,
                                 transform=s.window_transform(w), invert=True)
            sel = arr[mask & ~arr.mask]
            if sel.size and float(sel.max()) > mx:
                mx = float(sel.max())
    return None if mx == -np.inf else mx


def _parse_3dfier_obj_heights(tmp_dir: Path) -> dict[str, float]:
    """From each chunk_*.obj, derive per-building height = max(z) - min(z)
    for each ``g <OBJECTID>`` group."""
    heights: dict[str, float] = {}
    for obj_path in tmp_dir.glob("chunk_*.obj"):
        cur_id = None
        cur_min = np.inf; cur_max = -np.inf
        def _flush():
            nonlocal cur_min, cur_max
            if cur_id is not None and cur_max > cur_min:
                heights[cur_id] = cur_max - cur_min
        with obj_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("g "):
                    _flush()
                    cur_id = line[2:].strip()
                    cur_min = np.inf; cur_max = -np.inf
                elif line.startswith("v "):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            z = float(parts[3])
                        except Exception: continue
                        if z < cur_min: cur_min = z
                        if z > cur_max: cur_max = z
            _flush()
    return heights


def _pct(arr, p): return float(np.percentile(arr, p)) if len(arr) else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0,
                    help="Random sample size (0 = all)")
    ap.add_argument("--skip-mhc", action="store_true",
                    help="Skip MHC sampling (slow for 200k+)")
    args = ap.parse_args()

    try:
        import geopandas as gpd
        from shapely.strtree import STRtree
    except ImportError as e:
        print(f"Missing: {e}", file=sys.stderr); return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load RNCan (authoritative heights)
    print("[load] RNCan GPKG...")
    rncan_files = list(RNCAN_DIR.rglob("*.gpkg"))
    if not rncan_files:
        print("[err] no RNCan gpkg found", file=sys.stderr); return 2
    parts = [gpd.read_file(p) for p in rncan_files]
    rncan = gpd.GeoDataFrame(
        __import__("pandas").concat(parts, ignore_index=True),
        geometry="geometry", crs=parts[0].crs).to_crs(2949)
    print(f"[rnc] {len(rncan)} buildings")

    # 2. Load VdQ
    print("[load] VdQ GeoJSON...")
    vdq = gpd.read_file(VDQ_GJSON).to_crs(2949)
    print(f"[vdq] {len(vdq)} buildings")

    # 3. 3dfier heights
    if TDFIER_TMP.exists():
        print("[load] parsing 3dfier OBJ chunks...")
        tdf_heights = _parse_3dfier_obj_heights(TDFIER_TMP)
        print(f"[3df] {len(tdf_heights)} buildings with 3dfier height")
    else:
        tdf_heights = {}
        print("[3df] no 3dfier output yet")

    # 4. Sample
    if args.sample:
        rncan = rncan.sample(min(args.sample, len(rncan)), random_state=42) \
                     .reset_index(drop=True)
        print(f"[samp] random {len(rncan)}")

    # 5. Spatial join VdQ -> RNCan (closest centroid)
    print("[join] VdQ <-> RNCan (nearest)...")
    vdq["_c"] = vdq.geometry.centroid
    tree = STRtree(vdq["_c"].values)
    vdq_ids = []
    for g in rncan.geometry:
        c = g.centroid
        idxs = tree.query(c.buffer(5.0))
        if len(idxs):
            dists = [c.distance(vdq["_c"].iloc[int(i)]) for i in idxs]
            j = int(idxs[int(np.argmin(dists))])
            vdq_ids.append(str(vdq.iloc[j]["ID"]))
        else:
            vdq_ids.append(None)
    rncan["_vdq_id"] = vdq_ids

    # 6. MHC sample
    mhc_vals = [None] * len(rncan)
    if not args.skip_mhc:
        mhc_paths = sorted(MHC_DIR.glob("MHC_*.tif"))
        print(f"[mhc] sampling over {len(mhc_paths)} rasters (this is slow)...")
        for i, (_, r) in enumerate(rncan.iterrows()):
            if i % 1000 == 0:
                print(f"  {i}/{len(rncan)}")
            mhc_vals[i] = _mhc_sample_max(r.geometry, mhc_paths)
    rncan["_mhc"] = mhc_vals

    # 7. 3dfier match via centroid lookup (OBJECTID = VdQ ID or integer)
    rncan["_tdf_h"] = [tdf_heights.get(vid) if vid else None
                       for vid in rncan["_vdq_id"]]

    # 8. Compose output CSV
    out_csv = OUT_DIR / "heights_comparison.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["feature_id", "vdq_id", "area_m2",
                    "rncan_h_min", "rncan_h_max", "rncan_elev_min",
                    "mhc_max_m", "tdfier_h_m"])
        for _, r in rncan.iterrows():
            w.writerow([r["feature_id"], r["_vdq_id"],
                        round(float(r.get("bldgarea") or 0), 1),
                        r.get("heightmin"), r.get("heightmax"),
                        r.get("elevmin"),
                        (round(r["_mhc"], 2) if r["_mhc"] is not None else None),
                        (round(r["_tdf_h"], 2) if r["_tdf_h"] is not None else None)])

    # 9. Stats
    def arr(col): return rncan[col].dropna().astype(float).values
    stats = {
        "n_rncan": int(len(rncan)),
        "n_vdq_matched": int(sum(v is not None for v in rncan["_vdq_id"])),
        "n_mhc_matched": int(sum(v is not None for v in rncan["_mhc"])),
        "n_3dfier_matched": int(sum(v is not None for v in rncan["_tdf_h"])),
    }
    for col, key in [("heightmax", "rncan_hmax"), ("_mhc", "mhc"),
                     ("_tdf_h", "tdfier_h")]:
        a = arr(col) if col in rncan.columns else np.array([])
        if len(a):
            stats[key] = {
                "n": int(len(a)),
                "mean": round(float(np.mean(a)), 2),
                "median": round(_pct(a, 50), 2),
                "p05": round(_pct(a, 5), 2),
                "p95": round(_pct(a, 95), 2),
                "max": round(float(np.max(a)), 2),
            }

    # Deltas
    paired = rncan.dropna(subset=["heightmax", "_mhc"])
    if len(paired):
        d = paired["heightmax"].astype(float) - paired["_mhc"].astype(float)
        stats["rncan_minus_mhc"] = {
            "n": int(len(d)),
            "mean": round(float(d.mean()), 2),
            "median": round(float(d.median()), 2),
            "abs_mean": round(float(d.abs().mean()), 2),
            "p05": round(_pct(d.values, 5), 2),
            "p95": round(_pct(d.values, 95), 2),
        }
    paired = rncan.dropna(subset=["heightmax", "_tdf_h"])
    if len(paired):
        d = paired["heightmax"].astype(float) - paired["_tdf_h"].astype(float)
        stats["rncan_minus_3dfier"] = {
            "n": int(len(d)),
            "mean": round(float(d.mean()), 2),
            "median": round(float(d.median()), 2),
            "abs_mean": round(float(d.abs().mean()), 2),
            "p05": round(_pct(d.values, 5), 2),
            "p95": round(_pct(d.values, 95), 2),
        }

    (OUT_DIR / "heights_stats.json").write_text(json.dumps(stats, indent=2))
    print("\n=== Audit summary ===")
    print(json.dumps(stats, indent=2))
    print(f"\n[done] -> {out_csv.name}, heights_stats.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
