"""Enable Nanite + auto-generate LODs on converted SM tree assets.

Run after unreal_convert_sk_to_sm.py. Gives camera-distance-based auto
simplification: near = full detail, far = heavy simplification.

Run in UE Python Console:
  exec(open(r'C:/Users/franc/OneDrive/Documents/GitHub/RF-analysis/scripts/unreal_enable_nanite_lods.py').read())
"""
import unreal

SM_ROOT = "/Game/Megaplant_Library"
TARGETS = []
for sp, folder in [
    ("Tree_English_Oak",  "Tree_English_Oak_Forest_01/SM_English_Oak_Forest_01"),
    ("Tree_Norway_Maple", "Tree_Norway_Maple_Forest_01/SM_Norway_Maple_Forest_01"),
    ("Tree_Goat_Willow",  "Tree_Goat_Willow_01/SM_Goat_Willow_01"),
    ("Tree_Baltic_Pine",  "Tree_Baltic_Pine_01/SM_Baltic_Pine_01"),
]:
    for v in "ABCD":
        TARGETS.append(f"{SM_ROOT}/{sp}/{folder}_{v}")


# LOD screen-sizes (fraction of viewport). LOD0 = close, lower = farther.
LOD_SCREEN_SIZES = [1.0, 0.5, 0.15, 0.04]
LOD_TRI_PERCENT  = [1.0, 0.50, 0.15, 0.04]  # 0=full, then 50%, 15%, 4%


sme = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)


def apply(sm_path: str) -> bool:
    sm: unreal.StaticMesh = unreal.EditorAssetLibrary.load_asset(sm_path)
    if not sm:
        unreal.log_warning(f"[lod] missing: {sm_path}")
        return False

    # Enable Nanite.
    nanite = sm.get_editor_property("nanite_settings")
    nanite.enabled = True
    sm.set_editor_property("nanite_settings", nanite)

    # Auto-generate 4 LODs via StaticMeshEditorSubsystem.
    opts = unreal.EditorScriptingMeshReductionOptions()
    opts.auto_compute_lod_screen_size = False
    opts.reduction_settings = []
    for i, pct in enumerate(LOD_TRI_PERCENT):
        rs = unreal.EditorScriptingMeshReductionSettings()
        rs.percent_triangles = pct
        rs.screen_size = LOD_SCREEN_SIZES[i]
        opts.reduction_settings.append(rs)
    sme.set_lods(sm, opts)
    unreal.EditorAssetLibrary.save_loaded_asset(sm)
    unreal.log(f"[lod] OK: {sm.get_name()}")
    return True


ok = fail = 0
for p in TARGETS:
    if apply(p): ok += 1
    else: fail += 1
print(f"[lod] DONE: ok={ok} fail={fail}")
unreal.log(f"[lod] DONE: ok={ok} fail={fail}")
