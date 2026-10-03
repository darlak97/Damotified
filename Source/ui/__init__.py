import bpy
from bpy.props import IntProperty, BoolProperty, PointerProperty, CollectionProperty
from bpy.app.handlers import persistent

from .preferences import classes as pref_classes
from .panels import classes as panel_classes, DAMOTIFIED_DummyItem, DAMOTIFIED_ShapeUVItem
from .operators import classes as operator_classes, menu_func_import, get_mesh_from_bone

from ..debug import logger

classes = pref_classes + panel_classes + operator_classes

# ==============================================================================
# Debugging vars 
# ==============================================================================
_last_selected_bone_names = set()
_last_visibility_list_bone = None

# Sync locks for UIList - Depsgraph loops
_is_syncing_visibility = False
_is_syncing_shape_uv = False

# ==============================================================================
# Callbacks and filters
# ==============================================================================

def update_rig_index(self, context):
    idx = self.damotified_rig_index
    objects = context.scene.objects
    
    if 0 <= idx < len(objects):
        rig = objects[idx]
        if rig.type == 'ARMATURE':
            logger.debug(f"{{Rig Manager}} : Selected rig '{rig.name}'")
            if context.scene.attachment_armature != rig:
                context.scene.attachment_armature = rig
                logger.debug(f"{{Attachments}} : Auto-linked armature to '{rig.name}'")

def poll_armatures_only(self, object):
    return object.type == 'ARMATURE'

def update_animation_armature(self, context):
    if self.export_armature != self.animation_armature:
        self.export_armature = self.animation_armature

def update_export_armature(self, context):
    if self.animation_armature != self.export_armature:
        self.animation_armature = self.export_armature

def update_animation_index(self, context):
    idx = self.damotified_animation_index
    actions = bpy.data.actions
    
    if 0 <= idx < len(actions):
        selected_action = actions[idx]
        self.export_action = selected_action
        
        armature = self.animation_armature
        if armature and armature.type == 'ARMATURE':
            if not armature.animation_data:
                armature.animation_data_create()
            if armature.animation_data.action != selected_action:
                armature.animation_data.action = selected_action
                logger.debug(f"{{Animations}} : Applied action '{selected_action.name}' to '{armature.name}'")
    else:
        self.export_action = None

def update_visibility_index(self, context):
    global _last_visibility_list_bone, _is_syncing_visibility
    
    if _is_syncing_visibility:
        return
        
    _is_syncing_visibility = True
    try:
        armature = self.animation_armature
        idx = self.damotified_visibility_index
        
        if armature and armature.type == 'ARMATURE' and armature.data and context.mode == 'POSE':
            if 0 <= idx < len(armature.pose.bones):
                target_bone_name = armature.pose.bones[idx].name
                
                if target_bone_name != _last_visibility_list_bone:
                    logger.debug(f"{{Visibility List}} : Selected bone '{target_bone_name}'")
                    _last_visibility_list_bone = target_bone_name
                
                if context.active_pose_bone and context.active_pose_bone.name == target_bone_name:
                    return
                
                for p_bone in armature.pose.bones:
                    if hasattr(p_bone, 'select'):
                        p_bone.select = False
                    elif hasattr(p_bone.bone, 'select'):
                        p_bone.bone.select = False
                    
                target_p_bone = armature.pose.bones.get(target_bone_name)
                target_data_bone = armature.data.bones.get(target_bone_name)
                
                if target_p_bone and target_data_bone:
                    armature.data.bones.active = target_data_bone
                    if hasattr(target_p_bone, 'select'):
                        target_p_bone.select = True
                    elif hasattr(target_data_bone, 'select'):
                        target_data_bone.select = True
    finally:
        _is_syncing_visibility = False

def update_shape_uv_index(self, context):
    global _is_syncing_shape_uv
    if _is_syncing_shape_uv:
        return
        
    _is_syncing_shape_uv = True
    try:
        idx = self.damotified_shape_uv_index
        lst = self.damotified_shape_uv_list
        armature = self.animation_armature

        if 0 <= idx < len(lst) and armature:
            bone_name = lst[idx].name
            
            target_mesh = get_mesh_from_bone(armature, bone_name)

            if self.damotified_shape_uv_target != target_mesh:
                self.damotified_shape_uv_target = target_mesh
                if target_mesh:
                    logger.debug(f"{{Shape UV List}} : Switched to mesh '{target_mesh.name}'")

            if context.mode == 'POSE' and armature.data:
                target_p_bone = armature.pose.bones.get(bone_name)
                target_data_bone = armature.data.bones.get(bone_name)
                
                active_pose = context.active_pose_bone
                if not active_pose or active_pose.name != bone_name:
                    # Deselect bones
                    for p_bone in armature.pose.bones:
                        if hasattr(p_bone, 'select'):
                            p_bone.select = False
                        elif hasattr(p_bone.bone, 'select'):
                            p_bone.bone.select = False
                            
                    if target_p_bone and target_data_bone:
                        armature.data.bones.active = target_data_bone
                        if hasattr(target_p_bone, 'select'):
                            target_p_bone.select = True
                        elif hasattr(target_data_bone, 'select'):
                            target_data_bone.select = True
        else:
            if self.damotified_shape_uv_target is not None:
                self.damotified_shape_uv_target = None
    finally:
        _is_syncing_shape_uv = False
            
# ==============================================================================
# Handlers
# ==============================================================================

@persistent
def sync_bone_selection_to_list(scene, depsgraph):
    global _last_selected_bone_names, _is_syncing_visibility, _is_syncing_shape_uv
    
    # Block Depsgraph if updating via UI
    if _is_syncing_visibility or _is_syncing_shape_uv:
        return
        
    context = bpy.context
    armature = getattr(scene, "animation_armature", None)
    
    if armature and context.mode == 'POSE':
        current_selected_bones = set()
        for p_bone in armature.pose.bones:
            is_selected = getattr(p_bone, 'select', getattr(p_bone.bone, 'select', False))
            if is_selected:
                current_selected_bones.add(p_bone.name)
        
        if current_selected_bones != _last_selected_bone_names:
            _last_selected_bone_names = current_selected_bones.copy()
            if len(current_selected_bones) == 1:
                bone_name = list(current_selected_bones)[0]
                logger.debug(f"{{Viewport}} : Selected bone '{bone_name}'")
        
        active_bone = context.active_pose_bone
        is_active_selected = False
        if active_bone:
            is_active_selected = getattr(active_bone, 'select', getattr(active_bone.bone, 'select', False))
            
        if active_bone and active_bone.id_data == armature and is_active_selected:
            # Sync Visibility list
            idx_vis = armature.pose.bones.find(active_bone.name)
            if idx_vis != -1 and scene.damotified_visibility_index != idx_vis:
                _is_syncing_visibility = True
                try:
                    scene.damotified_visibility_index = idx_vis
                finally:
                    _is_syncing_visibility = False

            # Sync Shape UV list
            for i, item in enumerate(scene.damotified_shape_uv_list):
                if item.name == active_bone.name:
                    if scene.damotified_shape_uv_index != i:
                        _is_syncing_shape_uv = True
                        try:
                            scene.damotified_shape_uv_index = i
                            
                            # Update by block
                            target_mesh = get_mesh_from_bone(armature, item.name)
                            if scene.damotified_shape_uv_target != target_mesh:
                                scene.damotified_shape_uv_target = target_mesh
                        finally:
                            _is_syncing_shape_uv = False
                    break
    else:
        if _last_selected_bone_names:
            _last_selected_bone_names.clear()
        if scene.damotified_visibility_index != -1:
            scene.damotified_visibility_index = -1

@persistent
def sync_action_selection_to_list(scene, depsgraph):
    armature = getattr(scene, "animation_armature", None)
    if armature and armature.animation_data:
        active_action = armature.animation_data.action
        if active_action:
            idx = bpy.data.actions.find(active_action.name)
            if idx != -1 and scene.damotified_animation_index != idx:
                scene.damotified_animation_index = idx

@persistent
def sync_uv_animation(scene, depsgraph):
    """Syncs the Properties to the Mesh UV Proxy for the preview"""
    armature = getattr(scene, "animation_armature", None)
    if not armature or armature.type != 'ARMATURE':
        return
        
    for item in scene.damotified_shape_uv_list:
        p_bone = armature.pose.bones.get(item.name)
        if not p_bone: continue
        
        if "X shapeUvOffset" in p_bone and "Y shapeUvOffset" in p_bone:
            x_val = int(p_bone["X shapeUvOffset"])
            y_val = int(p_bone["Y shapeUvOffset"])
            
            target_mesh = get_mesh_from_bone(armature, item.name)
            
            if target_mesh:
                props = getattr(target_mesh, "uv_translate", None)
                if props:
                    # Update preview values
                    if props.px_x != x_val:
                        props.px_x = x_val
                    if props.px_y != y_val:
                        props.px_y = y_val
                        
# ==============================================================================
# Registration
# ==============================================================================

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
        
    addon_name = __package__.split(".")[0]
    prefs = bpy.context.preferences.addons.get(addon_name)
    if prefs and hasattr(prefs.preferences, 'debug_mode'):
        import logging
        logger.setLevel(logging.DEBUG if prefs.preferences.debug_mode else logging.WARNING)
    # Rig manager
    bpy.types.Scene.damotified_rig_index = IntProperty(
        name="Armature Index", 
        default=0, 
        update=update_rig_index
    )
    bpy.types.Scene.damotified_empty_collection = CollectionProperty(
        type=DAMOTIFIED_DummyItem
    )
    # - Attachments
    bpy.types.Scene.attachment_armature = PointerProperty(
        type=bpy.types.Object,
        name="Armature Target",
        poll=poll_armatures_only
    )
    bpy.types.Scene.damotified_attachment_index = IntProperty(
        name="Attachment Index",
        default=0
    )
    # Animations
    bpy.types.Scene.animation_armature = PointerProperty(
        type=bpy.types.Object,
        name="Armature Target",
        poll=poll_armatures_only,
        update=update_animation_armature
    )
    
    bpy.types.Scene.damotified_animation_index = IntProperty(
        name="Action Index",
        default=0,
        update=update_animation_index
    )
    # Visibility
    bpy.types.Scene.damotified_visibility_index = IntProperty(
        name="Visibility Hide Index",
        default=0,
        update=update_visibility_index
    )
    # Shape UV
    bpy.types.Scene.damotified_shape_uv_index = IntProperty(
        name="Shape UV Index",
        default=0,
        update=update_shape_uv_index
    )
    bpy.types.Scene.damotified_shape_uv_list = CollectionProperty(
        type=DAMOTIFIED_ShapeUVItem
    )
    bpy.types.Scene.damotified_shape_uv_target = PointerProperty(
        type=bpy.types.Object,
        name="Target Mesh"
    )
    # Export
    bpy.types.Scene.export_armature = PointerProperty(
        type=bpy.types.Object,
        name="Armature Target",
        poll=poll_armatures_only,
        update=update_export_armature
    )
    bpy.types.Scene.export_action = PointerProperty(
        type=bpy.types.Action,
        name="Action Target"
    )
    
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    
    if sync_uv_animation not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_uv_animation)
    
    if sync_bone_selection_to_list not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_bone_selection_to_list)
        
    if sync_action_selection_to_list not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(sync_action_selection_to_list)

def unregister():
    if sync_bone_selection_to_list in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_bone_selection_to_list)
        
    if sync_action_selection_to_list in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_action_selection_to_list)
    
    if sync_uv_animation in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(sync_uv_animation)
    
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    
    del bpy.types.Scene.damotified_rig_index
    del bpy.types.Scene.damotified_empty_collection
    del bpy.types.Scene.attachment_armature
    del bpy.types.Scene.damotified_attachment_index
    
    del bpy.types.Scene.animation_armature
    del bpy.types.Scene.damotified_animation_index
    del bpy.types.Scene.damotified_visibility_index
    del bpy.types.Scene.damotified_shape_uv_list
    del bpy.types.Scene.damotified_shape_uv_index
    del bpy.types.Scene.damotified_shape_uv_target
    
    del bpy.types.Scene.export_armature
    del bpy.types.Scene.export_action
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)