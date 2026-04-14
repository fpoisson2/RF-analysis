"""Automated PVE -> SM bake.

Spawns each Megaplant PVE actor, accumulates geometry from ALL its child
StaticMesh/ISM components (trunk + procedurally-placed leaves) into a
DynamicMesh via Geometry Script, saves as new SM_Full_* asset.

Assumptions:
- Geometry Script plugin enabled.
- PVEs generate their content in-editor on spawn (typical for Megaplant).

Run in UE Python Console:
  exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_bake_pve_to_sm.py').read())
"""
import unreal

SM_ROOT = "/Game/Megaplant_Library"

# (pve_asset_path, output_sm_path)
TARGETS = []
for species, folder, variant_prefix in [
    ("Tree_English_Oak",  "Tree_English_Oak_Forest_01",  "English_Oak_Forest_01"),
    ("Tree_Norway_Maple", "Tree_Norway_Maple_Forest_01", "Norway_Maple_Forest_01"),
    ("Tree_Goat_Willow",  "Tree_Goat_Willow_01",         "Goat_Willow_01"),
    ("Tree_Baltic_Pine",  "Tree_Baltic_Pine_01",         "Baltic_Pine_01"),
]:
    pve = f"{SM_ROOT}/{species}/{folder}/PVE_{variant_prefix}"
    out = f"{SM_ROOT}/{species}/{folder}/SM_FullFoliage_{variant_prefix}"
    TARGETS.append((pve, out))

editor_actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
STAGING_LOC = unreal.Vector(0, 0, -1000000)  # far below scene
LABEL = "_BakePVETmp"


def _collect_smcs(actor):
    """Walk all child components finding StaticMeshComponents (includes
    InstancedStaticMeshComponent subclass)."""
    out = []
    for c in actor.get_components_by_class(unreal.StaticMeshComponent):
        if c.get_static_mesh():
            out.append(c)
    return out


def bake(pve_path: str, sm_path: str) -> bool:
    if unreal.EditorAssetLibrary.does_asset_exist(sm_path):
        unreal.EditorAssetLibrary.delete_asset(sm_path)

    pve_asset = unreal.EditorAssetLibrary.load_asset(pve_path)
    if not pve_asset:
        unreal.log_warning(f"[bake] missing PVE: {pve_path}")
        return False
    unreal.log(f"[bake] PVE type: {type(pve_asset).__name__} "
               f"class={pve_asset.get_class().get_name()}")

    # Let UE's registered ActorFactory handle the asset (Megaplant plugin
    # provides one for 'ProceduralVegetation' type).
    actor = editor_actor_sub.spawn_actor_from_object(
        pve_asset, STAGING_LOC, unreal.Rotator(0, 0, 0))

    if not actor:
        unreal.log_warning(f"[bake] spawn failed: {pve_path}")
        return False
    actor.set_actor_label(LABEL)

    # Give the PVE a tick to generate its leaf instances (in-editor).
    # Some PVEs need a construction-script trigger:
    try:
        actor.rerun_construction_scripts()
    except Exception:
        pass

    smcs = _collect_smcs(actor)
    if not smcs:
        unreal.log_warning(f"[bake] no SM components under {pve_path}")
        editor_actor_sub.destroy_actor(actor)
        return False

    # Accumulate all component geometry (world-space within actor root)
    # into one DynamicMesh.
    dm = unreal.DynamicMesh()
    copy_opts = unreal.GeometryScriptCopyMeshFromComponentOptions()
    total_tris = 0
    for c in smcs:
        dm, _ = unreal.GeometryScript_CopyMeshFromComponent.copy_mesh_from_component(
            c, dm, copy_opts, True,  # bRequestedWorldSpace
            unreal.Transform())
        total_tris = dm.get_triangle_count()
    unreal.log(f"[bake] {pve_path} components={len(smcs)} tris={total_tris}")

    create_opts = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()
    sm, _ = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(
        dm, sm_path, create_opts)
    editor_actor_sub.destroy_actor(actor)
    if not sm:
        unreal.log_warning(f"[bake] asset create failed: {sm_path}")
        return False

    unreal.EditorAssetLibrary.save_asset(sm_path)
    unreal.log(f"[bake] OK: {sm_path}")
    return True


ok = fail = 0
for pve, sm in TARGETS:
    if bake(pve, sm): ok += 1
    else: fail += 1

# Cleanup any leftover tmp actor.
for a in editor_actor_sub.get_all_level_actors():
    if a.get_actor_label() == LABEL:
        editor_actor_sub.destroy_actor(a)

print(f"[bake] DONE: ok={ok} fail={fail}")
unreal.log(f"[bake] DONE: ok={ok} fail={fail}")
