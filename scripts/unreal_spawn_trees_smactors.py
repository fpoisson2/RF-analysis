"""Spawn trees as individual StaticMeshActors (not ISM).

Reason: Nanite Voxels foliage in UE 5.7 works on standalone
StaticMeshComponents but NOT on InstancedStaticMeshComponent, so the
ISM-batched version showed trunks without leaves.

Each tree = one StaticMeshActor. Heavier than ISM but WP streaming and
individual culling help. Expected ~150-500 MB just for actor data at
72k trees; SM meshes shared in memory.

Run in UE Python Console:
  exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_spawn_trees_smactors.py').read())
"""
import csv
import hashlib
import unreal

CSV_PATH = r"E:\rf_analysis\unreal\trees_ue\trees_ue.csv"
SM_ROOT = "/Game/Megaplant_Library"

GENUS_VARIANTS = {
    "oak":    [f"{SM_ROOT}/Tree_English_Oak/Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01_{c}" for c in "ABCD"],
    "maple":  [f"{SM_ROOT}/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01_{c}" for c in "ABCD"],
    "willow": [f"{SM_ROOT}/Tree_Goat_Willow/Tree_Goat_Willow_01/SM_Goat_Willow_01_{c}" for c in "ABCD"],
    "pine":   [f"{SM_ROOT}/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SM_Baltic_Pine_01_{c}" for c in "ABCD"],
}
GENUS_FALLBACK = {
    "spruce":"pine","fir":"pine","cedar":"pine","larch":"pine",
    "linden":"maple","elm":"maple","birch":"maple","poplar":"maple",
    "ash":"oak","beech":"oak","walnut":"oak","hickory":"oak",
    "cherry":"willow","apple":"willow","other":"maple",
}

MAX_TREES   = 0       # 0 = all
SAMPLE_STEP = 1       # 1 = every tree (bump if RAM tight)
EXTRA_Z     = 0
SCALE_CAP   = (0.3, 4.0)
LABEL_PREFIX = "Tree_"


def _hash_pick(seed: str, n: int) -> int:
    return int(hashlib.md5(seed.encode()).hexdigest()[:6], 16) % max(n, 1)


def _genus_of(group: str) -> str:
    return group.rsplit("_", 1)[0] if "_" in group else group


eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

# Purge any prior Tree_ actors.
_prior = [a for a in eas.get_all_level_actors()
          if a.get_actor_label().startswith(LABEL_PREFIX)]
if _prior:
    unreal.log(f"[trees-sma] deleting {len(_prior)} prior tree actors")
    eas.destroy_actors(_prior)

# Pre-load meshes + native heights.
_meshes: dict = {}
_native_h: dict = {}
for genus, paths in GENUS_VARIANTS.items():
    for p in paths:
        m = unreal.EditorAssetLibrary.load_asset(p)
        if not m:
            unreal.log_warning(f"[trees-sma] missing: {p}")
            continue
        bb = m.get_bounding_box()
        _meshes[p] = m
        _native_h[p] = max(float(bb.max.z - bb.min.z), 1.0)

if not _meshes:
    raise RuntimeError("No SM variants loaded.")


def _paths_for(group: str):
    g = _genus_of(group)
    if g not in GENUS_VARIANTS:
        g = GENUS_FALLBACK.get(g, "maple")
    return [p for p in GENUS_VARIANTS[g] if p in _meshes]


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

        paths = _paths_for(group)
        if not paths:
            skipped += 1; continue
        path = paths[_hash_pick(f"{x:.0f}_{y:.0f}", len(paths))]
        m = _meshes[path]

        target_cm = h_m * 100.0
        s = target_cm / _native_h[path]
        s = max(SCALE_CAP[0], min(SCALE_CAP[1], s))

        actor = eas.spawn_actor_from_object(
            m, unreal.Vector(x, y, z + EXTRA_Z),
            unreal.Rotator(roll=0, pitch=0, yaw=yaw))
        if not actor:
            skipped += 1; continue
        actor.set_actor_scale3d(unreal.Vector(s, s, s))
        actor.set_actor_label(f"{LABEL_PREFIX}{i}")
        added += 1
        if added % 5000 == 0:
            unreal.log(f"[trees-sma] {added} placed ...")

unreal.log(f"[trees-sma] DONE: added={added} skipped={skipped}")
print(f"[trees-sma] DONE: added={added} skipped={skipped}")
