"""Programmatic conversion of Megaplant SkeletalMesh (SK_) assets to
StaticMesh (SM_) using the GeometryScripting plugin (shipped with UE5).

Requires plugin "Geometry Script" enabled. After running, ISM-based
spawning becomes feasible for 72k+ trees.

Run in UE Python Console:
  exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_convert_sk_to_sm.py').read())
"""
import unreal

SK_ASSETS = [
    # (sk_path, sm_path) — sm assets land alongside the originals.
    ("/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SK_English_Oak_Forest_01_A",
     "/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01_A"),
    ("/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SK_English_Oak_Forest_01_B",
     "/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01_B"),
    ("/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SK_English_Oak_Forest_01_C",
     "/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01_C"),
    ("/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SK_English_Oak_Forest_01_D",
     "/Game/Megaplant_Library/Tree_English_Oak/Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01_D"),
    ("/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SK_Norway_Maple_Forest_01_A",
     "/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01_A"),
    ("/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SK_Norway_Maple_Forest_01_B",
     "/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01_B"),
    ("/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SK_Norway_Maple_Forest_01_C",
     "/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01_C"),
    ("/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SK_Norway_Maple_Forest_01_D",
     "/Game/Megaplant_Library/Tree_Norway_Maple/Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01_D"),
    ("/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SK_Goat_Willow_01_A",
     "/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SM_Goat_Willow_01_A"),
    ("/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SK_Goat_Willow_01_B",
     "/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SM_Goat_Willow_01_B"),
    ("/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SK_Goat_Willow_01_C",
     "/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SM_Goat_Willow_01_C"),
    ("/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SK_Goat_Willow_01_D",
     "/Game/Megaplant_Library/Tree_Goat_Willow/Tree_Goat_Willow_01/SM_Goat_Willow_01_D"),
    ("/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/Baltic_Pine_01_A",
     "/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SM_Baltic_Pine_01_A"),
    ("/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/Baltic_Pine_01_B",
     "/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SM_Baltic_Pine_01_B"),
    ("/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/Baltic_Pine_01_C",
     "/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SM_Baltic_Pine_01_C"),
    ("/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/Baltic_Pine_01_D",
     "/Game/Megaplant_Library/Tree_Baltic_Pine/Tree_Baltic_Pine_01/SM_Baltic_Pine_01_D"),
]

def convert(sk_path: str, sm_path: str) -> bool:
    # Delete any pre-existing SM so we rebuild with materials.
    if unreal.EditorAssetLibrary.does_asset_exist(sm_path):
        unreal.EditorAssetLibrary.delete_asset(sm_path)

    src = unreal.EditorAssetLibrary.load_asset(sk_path)
    if not src:
        unreal.log_warning(f"[conv] missing source: {sk_path}")
        return False
    if not isinstance(src, unreal.SkeletalMesh):
        unreal.log_warning(f"[conv] not a SkeletalMesh: {sk_path}")
        return False

    # Read SK reference pose into a DynamicMesh.
    dm = unreal.DynamicMesh()
    copy_opts_in = unreal.GeometryScriptCopyMeshFromAssetOptions()
    lod = unreal.GeometryScriptMeshReadLOD()
    lod.lod_index = 0
    dm, _ = unreal.GeometryScript_AssetUtils.copy_mesh_from_skeletal_mesh(
        src, dm, copy_opts_in, lod)

    # Create new SM asset directly from the DynamicMesh.
    create_opts = unreal.GeometryScriptCreateNewStaticMeshAssetOptions()

    sm, _ = unreal.GeometryScript_NewAssetUtils.create_new_static_mesh_asset_from_mesh(
        dm, sm_path, create_opts)
    if not sm:
        unreal.log_warning(f"[conv] create_new_static_mesh_asset failed: {sm_path}")
        return False

    # Re-assign materials from the SK (Geometry Script drops them).
    try:
        sk_mats = [sm_info.material_interface for sm_info in src.materials]
        sm_mats = sm.static_materials
        for idx, mat in enumerate(sk_mats):
            if idx < len(sm_mats) and mat is not None:
                sm_mats[idx].material_interface = mat
                if hasattr(sm_mats[idx], "material_slot_name"):
                    sm_mats[idx].material_slot_name = (
                        src.materials[idx].material_slot_name)
        sm.static_materials = sm_mats
        unreal.EditorAssetLibrary.save_loaded_asset(sm)
    except Exception as e:
        unreal.log_warning(f"[conv] material copy failed on {sm_path}: {e}")

    unreal.EditorAssetLibrary.save_asset(sm_path)
    unreal.log(f"[conv] OK: {sm_path} ({len(src.materials)} mats)")
    return True


ok = fail = 0
for sk, sm in SK_ASSETS:
    if convert(sk, sm): ok += 1
    else: fail += 1

print(f"[conv] DONE: ok={ok} fail={fail}")
unreal.log(f"[conv] DONE: ok={ok} fail={fail}")
