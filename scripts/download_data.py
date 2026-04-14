"""Download open-data sources needed for tree/building enrichment.

Sources:
  1. VdQ `arbres repertories`     — 104k municipal trees with species + DHP.
  2. VdQ `arbres remarquables`    — additional remarkable trees.
  3. MRNF carte ecoforestiere     — feuillet 21L (Quebec + surroundings),
                                    polygons with CL_HAUT / CL_DENS / GR_ESS.
  4. CMQ ortho 2021 tile index    — SHP + CSV listing GeoTIFF tile URLs
                                    (tiles themselves are downloaded on demand
                                    by scripts/run_deepforest.py).

All files land in data/vegetation/. Resumes partial downloads.
"""
from __future__ import annotations
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "vegetation"
OUT.mkdir(parents=True, exist_ok=True)

SOURCES = [
    ("vdq_arbres_repertories.geojson",
     "https://www.donneesquebec.ca/recherche/dataset/34103a43-3712-4a29-92e1-039e9188e915/"
     "resource/de031174-cbdf-4d69-869c-21cca8036279/download/vdq-arbrerepertorie.geojson"),
    ("vdq_arbres_remarquables.geojson",
     "https://www.donneesquebec.ca/recherche/dataset/bc5afddf-9439-4e96-84fb-f91847b722be/"
     "resource/bbdca0dd-82df-42f9-845b-32348debf8ab/download/vdq-arbrepotentielremarquable.geojson"),
    ("carte_eco_21L_gpkg.zip",
     "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/DONNEES_FOR_ECO_SUD/"
     "Cartes_ecoforestieres_perturbations/02-Donnees/Decoupage250K/21L/CARTE_ECO_MAJ_21L_GPKG.zip"),
    ("ecoforest_dictionary.xlsx",
     "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/Foret/DONNEES_FOR_ECO_SUD/"
     "Cartes_ecoforestieres_perturbations/01-Documentation/DICTIONNAIRE_CARTE_ECO_MAJ.xlsx"),
    ("cmq_ortho2021_tile_index.zip",
     "https://www.donneesquebec.ca/recherche/dataset/0b968d7d-c8e7-4345-96a0-6b6c5efde93a/"
     "resource/1197197a-0233-45b1-8119-c7f7e0a7a9ef/download/index_imagerie_cmq.zip"),
    ("cmq_ortho2021_tile_index.csv",
     "https://www.donneesquebec.ca/recherche/dataset/0b968d7d-c8e7-4345-96a0-6b6c5efde93a/"
     "resource/65e0ce06-97a7-47b2-b055-ca4710e3ddfb/download/indextuilesorthopphotos_2021.csv"),
]


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download(name: str, url: str) -> None:
    dest = OUT / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] {name} ({_fmt_bytes(dest.stat().st_size)})")
        return
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"[get ] {name}\n       <- {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "RF-analysis/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length", 0))
        got = 0
        chunk = 1 << 20
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            f.write(buf)
            got += len(buf)
            if total:
                pct = got / total * 100
                print(f"       {_fmt_bytes(got)} / {_fmt_bytes(total)} ({pct:5.1f}%)", end="\r")
        print()
    tmp.rename(dest)
    print(f"       ok -> {dest.relative_to(ROOT)}")


def main() -> int:
    errors = 0
    for name, url in SOURCES:
        try:
            download(name, url)
        except Exception as e:
            print(f"[FAIL] {name}: {e}", file=sys.stderr)
            errors += 1
    print(f"\nDone. {len(SOURCES) - errors}/{len(SOURCES)} ok. Output: {OUT}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
