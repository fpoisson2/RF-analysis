"""Spawn VdQ trees as SkeletalMeshActors using Megaplant SK_ assets.

Each tree picks an A/B/C/D variant by deterministic hash of position, so
neighbours look different. Scale is derived from the database height
(height_m) divided by the mesh's native height (from its bbox), so trees
match real LiDAR-measured heights.

Heavy on RAM at 72k actors — start with SAMPLE_STEP > 1 (e.g. 5 = 14k)
and validate before going to 1.

Run in UE Python Console:
  exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_spawn_trees_skm.py').read())
"""
import csv
import hashlib
import unreal

CSV_PATH = r"E:\rf_analysis\unreal\trees_ue\trees_ue.csv"

# Genus -> list of SK asset paths (variants picked by hash for variety).
# Closest-match policy: missing genera fall back to a similar tree.
SK_ROOT = "/Game/Megaplant_Library"
GENUS_VARIANTS = {
    "oak":    [f"{SK_ROOT}/Tree_English_Oak/Tree_English_Oak_Forest_01/SK_English_Oak_Forest_01_{c}"
               for c in "ABCD"],
    "maple":  [f"{SK_ROOT}/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SK_Norway_Maple_Forest_01_{c}"
               for c in "ABCD"],
    "willow": [f"{SK_ROOT}/Tree_Goat_Willow/Tree_Goat_Willow_01/SK_Goat_Willow_01_{c}"
               for c in "ABCD"],
    "pine":   [f"{SK_ROOT}/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SK_Baltic_Pine_01_{c}"
               for c in "ABCD"],
}

# Closest-genus fallback for North-American species we don't have meshes
# for. Conifers -> pine; broadleaves -> oak/maple/willow by morphology.
GENUS_FALLBACK = {
    "spruce":  "pine",   "fir":    "pine",   "cedar": "pine",
    "larch":   "pine",   "linden": "maple",  "ash":   "oak",
    "elm":     "maple",  "birch":  "maple",  "poplar": "maple",
    "beech":   "oak",    "walnut": "oak",    "hickory": "oak",
    "cherry":  "willow", "apple":  "willow",
    "other":   "maple",
}

MAX_TREES   = 0       # 0 = all
SAMPLE_STEP = 5       # start at 5 (14k trees) to validate; lower = more
EXTRA_Z     = 0
SCALE_CAP   = (0.5, 4.0)  # clamp final scale to a sane range

EXTRA_Z = 0
ACTOR_LABEL_PREFIX = "TreeSK_"


def _hash_pick(seed: str, n: int) -> int:
    return int(hashlib.md5(seed.encode()).hexdigest()[:6], 16) % max(n, 1)


def _genus_of(group: str) -> str:
    return group.rsplit("_", 1)[0] if "_" in group else group


editor_actor_subsystem = unreal.get_editor_subsystem(
    unreal.EditorActorSubsystem)

# Purge prior tree actors.
_prior = [a for a in editor_actor_subsystem.get_all_level_actors()
          if a.get_actor_label().startswith(ACTOR_LABEL_PREFIX)]
if _prior:
    unreal.log(f"[trees-skm] deleting {len(_prior)} prior actors")
    editor_actor_subsystem.destroy_actors(_prior)

# Pre-load all variants and compute their native height (cm) once.
_loaded: dict[str, unreal.SkeletalMesh] = {}
_native_h: dict[str, float] = {}

for genus, paths in GENUS_VARIANTS.items():
    for p in paths:
        sk = unreal.EditorAssetLibrary.load_asset(p)
        if not sk:
            unreal.log_warning(f"[trees-skm] missing: {p}")
            continue
        bb = sk.get_bounds()
        # bb is BoxSphereBounds; .box_extent is half-extent.
        h = float(bb.box_extent.z) * 2.0
        _loaded[p] = sk
        _native_h[p] = max(h, 1.0)
        unreal.log(f"[trees-skm] {sk.get_name()}  native_h={h:.0f} cm")

if not _loaded:
    raise RuntimeError("No Megaplant SK assets loaded.")


def _resolve_paths(group: str) -> list:
    g = _genus_of(group)
    if g not in GENUS_VARIANTS:
        g = GENUS_FALLBACK.get(g, "maple")
    return [p for p in GENUS_VARIANTS[g] if p in _loaded]


added = 0
skipped = 0
with open(CSV_PATH, encoding="utf-8") as f:
    r = csv.DictReader(f)
    for i, row in enumerate(r):
        if MAX_TREES and added >= MAX_TREES:
            break
        if i % SAMPLE_STEP != 0:
            continue
        try:
            x = float(row["x_cm"]); y = float(row["y_cm"])
            z = float(row["z_cm"] or 0)
            yaw = float(row["yaw_deg"])
            h_m = float(row.get("height_m") or 10.0)
            group = row.get("mesh_group", "other_m")
        except ValueError:
            skipped += 1; continue

        paths = _resolve_paths(group)
        if not paths:
            skipped += 1; continue
        path = paths[_hash_pick(f"{x:.0f}_{y:.0f}", len(paths))]
        sk = _loaded[path]

        # Scale so the spawned tree's height matches the LiDAR height.
        target_cm = h_m * 100.0
        s = target_cm / _native_h[path]
        s = max(SCALE_CAP[0], min(SCALE_CAP[1], s))

        actor = editor_actor_subsystem.spawn_actor_from_class(
            unreal.SkeletalMeshActor,
            unreal.Vector(x, y, z + EXTRA_Z),
            unreal.Rotator(roll=0, pitch=0, yaw=yaw))
        if not actor:
            skipped += 1; continue
        actor.skeletal_mesh_component.set_skeletal_mesh(sk)
        actor.set_actor_scale3d(unreal.Vector(s, s, s))
        actor.set_actor_label(f"{ACTOR_LABEL_PREFIX}{i}")
        added += 1
        if added % 500 == 0:
            unreal.log(f"[trees-skm] {added} placed ...")

unreal.log(f"[trees-skm] DONE: added={added} skipped={skipped}")
print(f"[trees-skm] DONE: added={added} skipped={skipped}")
