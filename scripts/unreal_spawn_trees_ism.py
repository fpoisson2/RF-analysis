"""Spawn VdQ trees via one InstancedStaticMeshComponent per (species,
variant). Uses the SM_ assets created by unreal_convert_sk_to_sm.py.

Per-tree:
  - Genus -> closest-match species (with fallback for NA genera)
  - Variant A/B/C/D picked by hash of (x,y) for neighbour variety
  - Scale = h_BD / mesh_native_height so tree height matches LiDAR

Run in UE Python Console:
  exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_spawn_trees_ism.py').read())
"""
import csv
import hashlib
import unreal

CSV_PATH = r"E:\rf_analysis\unreal\trees_ue\trees_ue.csv"
SM_ROOT = "/Game/Megaplant_Library"

# Genus -> list of SM asset paths (A/B/C/D).
GENUS_VARIANTS = {
    "oak":    [f"{SM_ROOT}/Tree_English_Oak/Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01_{c}" for c in "ABCD"],
    "maple":  [f"{SM_ROOT}/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01_{c}" for c in "ABCD"],
    "willow": [f"{SM_ROOT}/Tree_Goat_Willow/Tree_Goat_Willow_01/SM_Goat_Willow_01_{c}" for c in "ABCD"],
    "pine":   [f"{SM_ROOT}/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SM_Baltic_Pine_01_{c}" for c in "ABCD"],
}

# Closest-genus fallback for species we don't have a mesh for.
GENUS_FALLBACK = {
    "spruce": "pine",   "fir":    "pine",   "cedar":  "pine",
    "larch":  "pine",
    "linden": "maple",  "elm":    "maple",  "birch":  "maple",
    "poplar": "maple",
    "ash":    "oak",    "beech":  "oak",    "walnut": "oak",
    "hickory":"oak",
    "cherry": "willow", "apple":  "willow",
    "other":  "maple",
}

MAX_TREES   = 0      # 0 = all
SAMPLE_STEP = 1
EXTRA_Z     = 0
SCALE_CAP   = (0.3, 4.0)

ACTOR_LABEL = "TreesInstanced"


def _hash_pick(seed: str, n: int) -> int:
    return int(hashlib.md5(seed.encode()).hexdigest()[:6], 16) % max(n, 1)


def _genus_of(group: str) -> str:
    return group.rsplit("_", 1)[0] if "_" in group else group


editor_actor_subsystem = unreal.get_editor_subsystem(
    unreal.EditorActorSubsystem)

# Purge prior host actor.
_prior = [a for a in editor_actor_subsystem.get_all_level_actors()
          if a.get_actor_label() == ACTOR_LABEL]
if _prior:
    unreal.log(f"[trees-ism] deleting {len(_prior)} prior host(s)")
    editor_actor_subsystem.destroy_actors(_prior)

# Spawn a single host actor.
host = editor_actor_subsystem.spawn_actor_from_class(
    unreal.Actor, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
host.set_actor_label(ACTOR_LABEL)

sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
root_handle = sds.k2_gather_subobject_data_for_instance(host)[0]


def _make_ism_for(mesh):
    params = unreal.AddNewSubobjectParams(
        parent_handle=root_handle,
        new_class=unreal.InstancedStaticMeshComponent,
        blueprint_context=None)
    h, err = sds.add_new_subobject(params)
    if not err.is_empty():
        raise RuntimeError(f"add_new_subobject: {err}")
    comp = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
        sds.k2_find_subobject_data_from_handle(h))
    comp.set_static_mesh(mesh)
    return comp


# Pre-load all variants, compute native height (cm), create ISM per path.
_meshes: dict[str, unreal.StaticMesh] = {}
_native_h: dict[str, float] = {}
_isms: dict[str, unreal.InstancedStaticMeshComponent] = {}

for genus, paths in GENUS_VARIANTS.items():
    for p in paths:
        m = unreal.EditorAssetLibrary.load_asset(p)
        if not m:
            unreal.log_warning(f"[trees-ism] missing: {p}")
            continue
        bb = m.get_bounding_box()
        h = float(bb.max.z - bb.min.z)
        _meshes[p] = m
        _native_h[p] = max(h, 1.0)
        _isms[p] = _make_ism_for(m)
        unreal.log(f"[trees-ism] {m.get_name()}  native_h={h:.0f} cm")

if not _meshes:
    raise RuntimeError("No SM variants loaded. Run convert_sk_to_sm first.")


def _paths_for(group: str):
    g = _genus_of(group)
    if g not in GENUS_VARIANTS:
        g = GENUS_FALLBACK.get(g, "maple")
    return [p for p in GENUS_VARIANTS[g] if p in _meshes]


added = 0
skipped = 0
counts: dict[str, int] = {}
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

        target_cm = h_m * 100.0
        s = target_cm / _native_h[path]
        s = max(SCALE_CAP[0], min(SCALE_CAP[1], s))

        t = unreal.Transform(
            location=unreal.Vector(x, y, z + EXTRA_Z),
            rotation=unreal.Rotator(roll=0, pitch=0, yaw=yaw),
            scale=unreal.Vector(s, s, s))
        _isms[path].add_instance(t, world_space=True)
        counts[path] = counts.get(path, 0) + 1
        added += 1
        if added % 5000 == 0:
            unreal.log(f"[trees-ism] {added} instances ...")

unreal.log(f"[trees-ism] DONE: instances={added} skipped={skipped}")
print(f"[trees-ism] DONE: instances={added} skipped={skipped}")
for p, c in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {p.rsplit('/', 1)[1]:35s} {c:>6}")
