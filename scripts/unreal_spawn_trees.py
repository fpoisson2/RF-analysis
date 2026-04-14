"""Unreal Editor Python: spawn VdQ trees as individual StaticMeshActors.

Simple & reliable fallback. For very large counts (70k+), consider using
Foliage Mode to convert all placed meshes to foliage instances after
spawning.

Config:
  DEFAULT_MESH - path of a Static Mesh in /Game/
  MAX_TREES    - cap for testing (0 = no cap)
  SAMPLE_STEP  - keep every N-th tree (1 = all, 10 = 10% sample)

Run:
  exec(open(r"C:/.../scripts/unreal_spawn_trees.py").read())
"""
import csv
import unreal

CSV_PATH = r"E:\rf_analysis\unreal\trees_ue\trees_ue.csv"
DEFAULT_MESH = "/Game/Megaplant_Library/Tree_Goat_Willow/Instances/ASY_001"

MAX_TREES = 0          # 0 = all
SAMPLE_STEP = 1        # 1 = every tree
EXTRA_Z = 0            # manual tweak (cm) if pivot not at base.
SCALE_MULT = 10.0      # multiplies CSV scale (Megaplant ref ~1-2m).

# Mesh orientation fix. Megaplant trees often import Y-up or X-up; this
# rotator is composed with yaw (pitch, yaw, roll). Try:
#   (-90, 0, 0)  if tree lies on its side along +X
#   (0, 0, -90)  if tree lies on its side along +Y
#   (0, 0, 0)    if tree is already Z-up
MESH_PITCH = 0
MESH_ROLL  = 0


def _load_mesh(path: str):
    return unreal.EditorAssetLibrary.load_asset(path)


mesh = _load_mesh(DEFAULT_MESH)
if not mesh:
    raise RuntimeError(f"Mesh not found: {DEFAULT_MESH}")

unreal.log(f"[trees] mesh: {mesh.get_name()}")

# Log bbox so user can inspect native mesh orientation.
_bb = mesh.get_bounding_box()
unreal.log(f"[trees] mesh bbox min=({_bb.min.x:.1f},{_bb.min.y:.1f},"
           f"{_bb.min.z:.1f}) max=({_bb.max.x:.1f},{_bb.max.y:.1f},"
           f"{_bb.max.z:.1f})")

editor_actor_subsystem = unreal.get_editor_subsystem(
    unreal.EditorActorSubsystem)
world = unreal.get_editor_subsystem(
    unreal.UnrealEditorSubsystem).get_editor_world()

# Purge previous Tree_* actors to avoid duplicates on re-run.
_all_actors = editor_actor_subsystem.get_all_level_actors()
_to_delete = [a for a in _all_actors
              if a.get_actor_label().startswith("Tree_")]
if _to_delete:
    unreal.log(f"[trees] deleting {len(_to_delete)} existing Tree_* actors")
    editor_actor_subsystem.destroy_actors(_to_delete)


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
            s = float(row["scale"]); yaw = float(row["yaw_deg"])
        except ValueError:
            skipped += 1; continue

        z_final = z + EXTRA_Z
        actor = editor_actor_subsystem.spawn_actor_from_object(
            mesh,
            unreal.Vector(x, y, z_final),
            unreal.Rotator(roll=MESH_ROLL, pitch=MESH_PITCH, yaw=yaw))
        if actor:
            ss = s * SCALE_MULT
            actor.set_actor_scale3d(unreal.Vector(ss, ss, ss))
            actor.set_actor_label(f"Tree_{i}")
            added += 1
            if added % 500 == 0:
                unreal.log(f"[trees] {added} placed ...")
        else:
            skipped += 1

unreal.log(f"[trees] DONE: added={added} skipped={skipped}")
print(f"[trees] DONE: added={added} skipped={skipped}")
print("\nIn UE, go to Mode -> Foliage. Select-all the Tree_* actors and "
      "click 'Convert to Foliage' for optimized rendering.")
