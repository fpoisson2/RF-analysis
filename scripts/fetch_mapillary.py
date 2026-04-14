"""Module 5a — Mapillary API → street furniture GeoJSON.

Fetches the Mapillary v4 ``map_features`` endpoint within a bbox around
a centre point, for a list of object classes (traffic signs, lights,
benches, fire hydrants, bike racks). Writes one GeoJSON per class into
``data/street_furniture/``.

Set MAPILLARY_TOKEN env var (OAuth client token; free tier is fine for
this volume). Docs: https://www.mapillary.com/developer/api-documentation

Usage:
    export MAPILLARY_TOKEN=MLY|...
    python scripts/fetch_mapillary.py --lat 46.8139 --lon -71.2080 --km 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "street_furniture"

OBJECT_CLASSES = [
    # (mapillary_value, output_filename, brief)
    ("object--traffic-light",        "traffic_lights.geojson",  "traffic light"),
    ("object--traffic-sign",         "traffic_signs.geojson",   "traffic sign"),
    ("object--street-light",         "street_lights.geojson",   "street light"),
    ("object--bench",                "benches.geojson",         "bench"),
    ("object--fire-hydrant",         "fire_hydrants.geojson",   "fire hydrant"),
    ("object--bike-rack",            "bike_racks.geojson",      "bike rack"),
    ("object--trash-can",            "trash_cans.geojson",      "trash can"),
    ("object--manhole",              "manholes.geojson",        "manhole"),
    ("object--mailbox",              "mailboxes.geojson",       "mailbox"),
]

API = "https://graph.mapillary.com/map_features"


def _fetch_class(token: str, bbox: str, value: str) -> list[dict]:
    params = {
        "access_token": token,
        "fields": "id,object_value,geometry,first_seen_at,last_seen_at",
        "bbox": bbox,
        "object_values": value,
        "limit": 2000,
    }
    url = API + "?" + urllib.parse.urlencode(params)
    out = []
    while url:
        req = urllib.request.Request(url, headers={"User-Agent": "RF-analysis/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = json.loads(r.read())
        except Exception as e:
            print(f"  [err] {e}", file=sys.stderr); break
        for item in payload.get("data", []):
            g = item.get("geometry") or {}
            c = g.get("coordinates") or []
            if len(c) < 2: continue
            out.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": c},
                "properties": {
                    "id": item.get("id"),
                    "class": item.get("object_value"),
                    "first_seen_at": item.get("first_seen_at"),
                    "last_seen_at": item.get("last_seen_at"),
                },
            })
        url = (payload.get("paging") or {}).get("next")
        time.sleep(0.15)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=46.8139)
    ap.add_argument("--lon", type=float, default=-71.2080)
    ap.add_argument("--km", type=float, default=10.0)
    ap.add_argument("--token", default=os.environ.get("MAPILLARY_TOKEN"))
    args = ap.parse_args()

    if not args.token:
        print("[err] MAPILLARY_TOKEN not set. Get one at https://www.mapillary.com/developer",
              file=sys.stderr); return 2

    import math
    dlat = args.km / 111.32
    dlon = args.km / (111.32 * math.cos(math.radians(args.lat)))
    bbox = f"{args.lon - dlon},{args.lat - dlat},{args.lon + dlon},{args.lat + dlat}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for value, fname, label in OBJECT_CLASSES:
        out_path = OUT_DIR / fname
        if out_path.exists():
            print(f"[skip] {fname}"); continue
        print(f"[get ] {label:20s} …", end="", flush=True)
        feats = _fetch_class(args.token, bbox, value)
        out_path.write_text(json.dumps({
            "type": "FeatureCollection", "features": feats
        }))
        total += len(feats)
        print(f" {len(feats):>6}")

    print(f"[done] {total} total features → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
