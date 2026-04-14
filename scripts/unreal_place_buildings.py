"""Unreal Engine 5 Editor Utility Python script.

Place ALL imported building chunk meshes at their correct MTM7 positions,
aligned with the landscape at world origin.

Usage INSIDE Unreal Editor:
  1. Edit -> Plugins -> enable "Python Editor Script Plugin" (if not already)
  2. Window -> Python Console
  3. Execute: exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_place_buildings.py').read())

What it does:
  * Reads heightmap manifest (origin_x_m, origin_y_m in MTM7 EPSG:2949).
  * Finds every Static Mesh asset whose name starts with "chunk_".
  * For each, reads its bounding box (which is in MTM7 cm due to Build Scale=100).
  * Computes actor location = (bbox_center_mtm_cm - origin_mtm_cm) to shift
    the mesh onto the landscape.
  * Spawns a StaticMeshActor at that location with Actor Scale = (1,-1,1)
    (Y flipped because UE Landscape uses +Y=South while MTM+Y=North).

Run again safely -- existing actors with matching names are skipped.
"""
import json
import unreal  # noqa

# --- config --------------------------------------------------------------
MANIFEST = r"C:\Users\franc\OneDrive\Documents\GitHub\RF-analysis\data\unreal\heightmap\manifest_single.json"
BUILDINGS_DIR_IN_CB = "/Game/"  # root where you imported chunks
BUILDING_PREFIX = "chunk_"     # only meshes whose name starts with this
FLIP_Y = True                   # True if landscape +Y points South

# --- load heightmap origin (MTM7 metres) --------------------------------
with open(MANIFEST) as f:
    manifest = json.load(f)
origin_x_m = float(manifest["origin_x_m"])
origin_y_m = float(manifest["origin_y_m"])
unreal.log(f"[place] landscape origin MTM7: ({origin_x_m}, {origin_y_m})")

# --- enumerate chunk assets ---------------------------------------------
ar = unreal.AssetRegistryHelpers.get_asset_registry()
assets = ar.get_assets_by_path(BUILDINGS_DIR_IN_CB, recursive=True)
chunk_assets = [a for a in assets
                if a.asset_class_path.asset_name == "StaticMesh"
                and str(a.asset_name).startswith(BUILDING_PREFIX)]
unreal.log(f"[place] found {len(chunk_assets)} chunk meshes")

# --- spawn actors --------------------------------------------------------
world = unreal.EditorLevelLibrary.get_editor_world()
existing = {a.get_actor_label(): a for a in unreal.EditorLevelLibrary
            .get_all_level_actors()}
spawned = 0
skipped = 0

for a in chunk_assets:
    mesh = unreal.EditorAssetLibrary.load_asset(a.package_name)
    if not mesh:
        continue
    name = str(a.asset_name)
    if name in existing:
        skipped += 1; continue

    # Bounding box in local coords (cm, because Build Scale 100 applied at
    # import baked the MTM metres into cm units).
    bb = mesh.get_bounding_box()
    min_v = bb.min
    max_v = bb.max
    # Center of mesh in MTM7 cm (same as local-space center since we don't
    # translate inside the mesh itself).
    cx_cm = (min_v.x + max_v.x) * 0.5
    cy_cm = (min_v.y + max_v.y) * 0.5

    # Desired actor location so that bbox centre lands at
    # (cx_cm - origin_x_m*100, origin_y_m*100 - cy_cm) in UE.
    target_x = cx_cm - origin_x_m * 100.0
    target_y = (origin_y_m * 100.0 - cy_cm) if FLIP_Y else (cy_cm - origin_y_m * 100.0)

    # The actor location must offset the stored mesh centre so the bbox ends
    # at target_x/target_y. Actor scale Y = -1 flips, so the mesh centre lands
    # at (cx_cm + actor.x, -cy_cm + actor.y). We want:
    #   cx_cm + actor.x = target_x          -> actor.x = -origin_x_m*100
    #   -cy_cm + actor.y = target_y (= origin_y*100 - cy)
    #                                       -> actor.y = origin_y_m*100
    location = unreal.Vector(
        -origin_x_m * 100.0,
        (origin_y_m * 100.0) if FLIP_Y else (-origin_y_m * 100.0),
        0.0,
    )
    scale = unreal.Vector(1.0, -1.0 if FLIP_Y else 1.0, 1.0)

    actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
        mesh, location, unreal.Rotator(0, 0, 0))
    if actor:
        actor.set_actor_label(name)
        actor.set_actor_scale3d(scale)
        spawned += 1

unreal.log(f"[place] spawned={spawned} skipped={skipped}")
print(f"[place] spawned={spawned} skipped={skipped}")
