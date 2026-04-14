"""Enable 'Used with Static Mesh' + 'Used with Instanced Static Meshes'
on all materials referenced by converted tree SM assets.

This is usually why leaves disappear after SK->SM conversion: the parent
Material has only 'UsedWithSkeletalMesh' flagged, so UE skips rendering
when the material is applied to an ISM.
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

# Walk up Material Instance parents to find the root Material.
def _root_material(m):
    while isinstance(m, unreal.MaterialInstance):
        parent = m.get_editor_property("parent")
        if not parent: return m
        m = parent
    return m

seen = set()
fixed = 0
for sm_path in TARGETS:
    sm = unreal.EditorAssetLibrary.load_asset(sm_path)
    if not sm:
        continue
    for slot in sm.static_materials:
        mi = slot.material_interface
        if not mi: continue
        root = _root_material(mi)
        if not root or root.get_path_name() in seen: continue
        seen.add(root.get_path_name())
        changed = False
        for flag in ("used_with_static_lighting",
                     "used_with_instanced_static_meshes",
                     "used_with_nanite"):
            try:
                if not root.get_editor_property(flag):
                    root.set_editor_property(flag, True)
                    changed = True
            except Exception:
                pass
        if changed:
            unreal.EditorAssetLibrary.save_loaded_asset(root)
            unreal.log(f"[mat] fixed: {root.get_name()}")
            fixed += 1

print(f"[mat] DONE: {fixed} root materials updated, {len(seen)} seen")
unreal.log(f"[mat] DONE: {fixed}/{len(seen)} materials updated")
