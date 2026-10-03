import bpy
from bpy.types import Panel, UIList, PropertyGroup
from ..shape_uv.main_uv_offset import draw_uvtx_panel
from ..debug import logger
from .operators import get_hide_keyframe_frames

class DAMOTIFIED_DummyItem(PropertyGroup):
    """ Placeholder for collection pointers."""
    pass

# =========================================================
# Utilities
# =========================================================

def is_plugin_configured(context):
    """ State from addon preferences."""
    addon_name = __package__.rsplit('.', 1)[0]
    prefs = context.preferences.addons.get(addon_name)
    
    is_permanently_hidden = prefs.preferences.is_configured if prefs else False
    is_file_configured = context.scene.get("damotified_is_configured", False)
    
    return is_permanently_hidden or is_file_configured

# =========================================================
# Welcome Panel
# =========================================================

class DAMOTIFIED_PT_initial_panel(Panel):
    """ Displays the initial welcome dialog."""
    bl_label = "Damotified"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    
    @classmethod
    def poll(cls, context):
        return not is_plugin_configured(context)
        
    def draw(self, context):
        layout = self.layout
        box = layout.box()
        row = box.row()
        
        row.label(text="Caution", icon='ERROR')
        box.label(text="Project in development.")
        
        layout.separator()
        layout.operator("damotified.start_configuration", icon='PREFERENCES')

# =========================================================
# Rig Manager
# =========================================================

class DAMOTIFIED_UL_rigs(UIList):
    """ UIList to display and filter Armature."""
    def filter_items(self, context, data, property):
        objects = getattr(data, property)
        flt_flags = []
        flt_neworder = []
        
        for obj in objects:
            if obj.type == 'ARMATURE':
                flt_flags.append(self.bitflag_filter_item)
            else:
                flt_flags.append(0)
                
        return flt_flags, flt_neworder
        
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.name, icon='OUTLINER_OB_ARMATURE')
            
            rig_col = bpy.data.collections.get(item.name)
            is_hidden = rig_col.hide_viewport if rig_col else item.hide_viewport
            icon_eye = 'HIDE_ON' if is_hidden else 'HIDE_OFF'
            
            op_vis = row.operator(
                "damotified.toggle_rig_visibility",
                text="", icon=icon_eye, emboss=False
            )
            op_vis.rig_name = item.name
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_OB_ARMATURE')

class DAMOTIFIED_UL_attachments(UIList):
    """ UIList to display imported attachment collections."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if hasattr(item, "name"):
                layout.label(text=item.name, icon='OUTLINER_COLLECTION')
                
                if hasattr(item, "hide_viewport"):
                    icon_eye = ('HIDE_OFF', 'HIDE_ON')[item.hide_viewport]
                    
                    op = layout.operator(
                        "damotified.toggle_attachment_visibility",
                        text="",
                        icon=icon_eye,
                        emboss=False
                    )
                    op.collection_name = item.name
                    
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_COLLECTION')

class DAMOTIFIED_PT_rig_manager(Panel):
    """ Main panel for managing imported rigs."""
    bl_idname = "DAMOTIFIED_PT_rig_manager"
    bl_label = "Rig Manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    
    @classmethod
    def poll(cls, context):
        return is_plugin_configured(context)
        
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        row = layout.row()
        row.template_list(
            "DAMOTIFIED_UL_rigs",
            "damotified_rigs_list",
            scene,
            "objects",
            scene,
            "damotified_rig_index",
            rows=3
        )
        
        col_btn = row.column(align=True)
        add_op = col_btn.operator("damotified.import_unified", text="", icon='ADD')
        add_op.import_type = 'RIG'
        
        sub_col = col_btn.column(align=True)
        
        idx = scene.damotified_rig_index
        objects = scene.objects
        
        if 0 <= idx < len(objects) and objects[idx].type == 'ARMATURE':
            current_rig_name = objects[idx].name
            sub_col.enabled = True
            rem_op = sub_col.operator("damotified.remove_rig", text="", icon='REMOVE')
            rem_op.rig_name = current_rig_name
        else:
            sub_col.enabled = False
            sub_col.operator("damotified.remove_rig", text="", icon='REMOVE')

class DAMOTIFIED_PT_attachments(Panel):
    """SubPanel for importing and managing attachment."""
    bl_idname = "DAMOTIFIED_PT_attachments"
    bl_parent_id = "DAMOTIFIED_PT_rig_manager"
    bl_label = "Attachments"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        
        layout.prop(context.scene, "attachment_armature", text="Armature", icon='OUTLINER_OB_ARMATURE')

        armature_obj = context.scene.attachment_armature
        
        dataptr = context.scene
        propname = "damotified_empty_collection"
        
        if armature_obj: 
            rig_collection = bpy.data.collections.get(armature_obj.name)
            
            if rig_collection:
                attachments_parent = next(
                    (child for child in rig_collection.children if child.name.startswith("Attachments_Meshes")),
                    None
                )
                
                if attachments_parent:
                    dataptr = attachments_parent
                    propname = "children"
                
        row = layout.row()
        row.template_list(
            "DAMOTIFIED_UL_attachments",
            "damotified_attachments_list",
            dataptr,
            propname,
            context.scene,
            "damotified_attachment_index",
            rows=3
        )
        
        col_btn = row.column(align=True)
        col_btn.enabled = armature_obj is not None
        
        add_op = col_btn.operator("damotified.import_unified", text="", icon='ADD')
        add_op.import_type = 'ATTACHMENT'
        
        sub_col = col_btn.column(align=True)
        has_items = False
        
        if armature_obj: 
            rig_col = bpy.data.collections.get(armature_obj.name)
            
            if rig_col:
                attachments_parent = next(
                    (child for child in rig_col.children if child.name.startswith("Attachments_Meshes")),
                    None
                )
                
                if attachments_parent and len(attachments_parent.children) > 0:
                    has_items = True
                
        sub_col.enabled = has_items
        sub_col.operator("damotified.remove_attachment", text="", icon='REMOVE')

# =========================================================
# Animations
# =========================================================

class DAMOTIFIED_UL_animations(UIList):
    """ UIList to display Actions."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        armature = context.scene.animation_armature
        active_action = None
        
        if armature and armature.animation_data:
            active_action = armature.animation_data.action
            
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            
            if item != active_action:
                row.active = False
                
            row.label(text=item.name, icon='ACTION')
            row.prop(item, "use_fake_user", text="", icon="FAKE_USER_OFF", emboss=False)
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='ACTION')

class DAMOTIFIED_PT_animations(Panel):
    """ Panel for assigning animation actions to armatures."""
    bl_idname = "DAMOTIFIED_PT_animations"
    bl_label = "Animations"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    
    @classmethod
    def poll(cls, context):
        return is_plugin_configured(context)
        
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        box = layout.box()
        
        box.prop(scene, "animation_armature", text="Armature", icon='OUTLINER_OB_ARMATURE')
        
        row = box.row()
        row.enabled = scene.animation_armature is not None
        
        row.template_list(
            "DAMOTIFIED_UL_animations",
            "damotified_animations_list",
            bpy.data,
            "actions",
            scene,
            "damotified_animation_index",
            rows=1,
            maxrows=2
        )
        
class DAMOTIFIED_UL_animation_visibility(UIList):
    """Custom UIList to display bones, hide keyframes."""
    def filter_items(self, context, data, property):
        bones = getattr(data, property)
        flt_flags = []
        flt_neworder = []
        
        scene = context.scene
        actions = bpy.data.actions
        idx = scene.damotified_animation_index
        
        action = actions[idx] if 0 <= idx < len(actions) else None
        
        hide_paths = set()
        
        if action:
            action_fcurves = []
            
            # Compatibility with legacy actions pre-Blender 5.0
            if hasattr(action, 'fcurves'):
                action_fcurves.extend(list(action.fcurves))
            
            # Support for Blender 5.0+ slotted actions
            if hasattr(action, 'layers'):
                for layer in action.layers:
                    if hasattr(layer, 'strips'):
                        for strip in layer.strips:
                            if hasattr(strip, 'channelbag') and strip.channelbag:
                                if hasattr(strip.channelbag, 'fcurves'):
                                    action_fcurves.extend(list(strip.channelbag.fcurves))
                                    
                            if hasattr(strip, 'channelbags'):
                                for cb in strip.channelbags:
                                    if hasattr(cb, 'fcurves'):
                                        action_fcurves.extend(list(cb.fcurves))

            for fc in action_fcurves:
                dp = getattr(fc, 'data_path', getattr(fc, 'rna_path', ''))
                
                if "hide" in dp.lower():
                    hide_paths.add(dp)
        
        for bone in bones:
            bone_target = f'"{bone.name}"'
            
            if any(bone_target in dp for dp in hide_paths):
                flt_flags.append(self.bitflag_filter_item)
            else:
                flt_flags.append(0)
                
        return flt_flags, flt_neworder
        
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name, icon='BONE_DATA')
            row = layout.row(align=True)
            
            row.prop(item, "hide", text="", icon='HIDE_OFF', emboss=False)
            row.prop_decorator(item, "hide")
            
            op_clear = row.operator("damotified.clear_hide_keyframes", text="", icon='PANEL_CLOSE', emboss=False)
            op_clear.bone_name = item.name
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='BONE_DATA')

class DAMOTIFIED_PT_animation_visibility(Panel):
    """ Controls to animate bone visibility."""
    bl_idname = "DAMOTIFIED_PT_animation_visibility"
    bl_parent_id = "DAMOTIFIED_PT_animations"
    bl_label = "Visibility"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        armature = scene.animation_armature
        
        if armature and armature.type == 'ARMATURE' and armature.pose:
            selected_bones = []
            
            for p_bone in armature.pose.bones:
                is_selected = getattr(p_bone, 'select', getattr(p_bone.bone, 'select', False))
                
                if is_selected:
                    selected_bones.append(p_bone)

            if selected_bones:
                box = layout.box()
                row = box.row(align=True)
                
                if len(selected_bones) == 1:
                    bone = selected_bones[0]
                    row.label(text=bone.name, icon='BONE_DATA')
                    row.prop(bone, "hide", text="", icon='HIDE_OFF', emboss=False)
                    row.prop_decorator(bone, "hide")
                else:
                    row.label(text=f"Selected Bones ({len(selected_bones)})", icon='BONE_DATA')
                    active_bone = context.active_pose_bone
                    
                    if not active_bone or active_bone not in selected_bones:
                        active_bone = selected_bones[0]
                        
                    current_hide = active_bone.hide
                    
                    op_hide = row.operator("damotified.hide_selected_bones", text="", icon='HIDE_OFF', emboss=False)
                    op_hide.hide_state = not current_hide
                    row.operator("damotified.keyframe_selected_bones", text="", icon='BONE_DATA', emboss=False)

                action = None
                actions = bpy.data.actions
                idx = scene.damotified_animation_index
                
                if 0 <= idx < len(actions):
                    action = actions[idx]
                    
                bone_names = [b.name for b in selected_bones]
                kf_frames = get_hide_keyframe_frames(action, bone_names)
                
                row_kf = box.row()
                row_kf.label(text=f"Keyframes: {len(kf_frames)}")
                
                nav_row = row_kf.row(align=True)
                nav_row.alignment = 'RIGHT'
                
                op_prev = nav_row.operator("damotified.jump_hide_keyframe", text="", icon='TRIA_LEFT')
                op_prev.direction = 'PREV'
                
                op_next = nav_row.operator("damotified.jump_hide_keyframe", text="", icon='TRIA_RIGHT')
                op_next.direction = 'NEXT'

            else:
                layout.label(text="Selected: None", icon='INFO')

            layout.template_list(
                "DAMOTIFIED_UL_animation_visibility",
                "damotified_visibility_list",
                armature.pose,
                "bones",
                scene,
                "damotified_visibility_index",
                rows=3
            )
        else:
            layout.label(text="Select an Armature above", icon='INFO')
            
class DAMOTIFIED_ShapeUVItem(PropertyGroup):
    """ Property group in UV list."""
    pass
    
class DAMOTIFIED_UL_shape_uv(UIList):
    """ UIList to manage bones with UV translation data."""
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.label(text=item.name, icon='BONE_DATA')
            
            op = row.operator("damotified.keyframe_shape_uv", text="", icon='KEYFRAME', emboss=False)
            op.bone_name = item.name
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='BONE_DATA')

class DAMOTIFIED_PT_shape_uv(Panel):
    """ Exposing the UV translations for facial expressions."""
    bl_idname = "DAMOTIFIED_PT_shape_uv"
    bl_parent_id = "DAMOTIFIED_PT_animations"
    bl_label = "Shape UV"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        armature = scene.animation_armature
        
        if not armature or armature.type != 'ARMATURE':
            layout.label(text="Select an Armature above", icon='INFO')
            return
            
        row = layout.row()
        row.template_list(
            "DAMOTIFIED_UL_shape_uv",
            "",
            scene,
            "damotified_shape_uv_list",
            scene,
            "damotified_shape_uv_index",
            rows=1,
            maxrows=2
        )
        
        col = row.column(align=True)
        
        sub_add = col.row()
        sub_add.operator("damotified.shape_uv_add", text="", icon='ADD')
        
        sub_rem = col.row()
        sub_rem.enabled = len(scene.damotified_shape_uv_list) > 0
        sub_rem.operator("damotified.shape_uv_remove", text="", icon='REMOVE')
        
        if len(scene.damotified_shape_uv_list) > 0:
            target_obj = scene.damotified_shape_uv_target
            
            prefs = context.preferences.addons.get("Damotified")
            is_debug = prefs.preferences.debug_mode if prefs else False
            
            if not target_obj:
                box = layout.box()
                box.label(text="No Mesh detected", icon='ERROR')
            else:
                if is_debug:
                    box = layout.box()
                    box.label(text=f"Mesh: {target_obj.name}", icon='MESH_DATA')
                
                draw_uvtx_panel(self, context)

# =========================================================
# Exporter
# =========================================================

class DAMOTIFIED_PT_exporting(Panel):
    """Main panel providing access to BlockyAnim exporter."""
    bl_idname = "DAMOTIFIED_PT_exporting"
    bl_label = "Exporting"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    
    @classmethod
    def poll(cls, context):
        return is_plugin_configured(context)
        
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        box = layout.box()
        
        box.prop(scene, "export_armature", text="Armature", icon='OUTLINER_OB_ARMATURE')
        box.prop(scene, "export_action", text="Action", icon='ACTION')
        
        row = box.row()
        
        row.enabled = (scene.export_armature is not None) and (scene.export_action is not None)
        
        row.operator("damotified.export_blockyanim", text="Export BlockyAnim", icon='EXPORT')

# =========================================================
# Registration
# =========================================================

classes = (
    DAMOTIFIED_DummyItem,
    DAMOTIFIED_UL_rigs,
    DAMOTIFIED_UL_attachments,
    DAMOTIFIED_PT_initial_panel,
    DAMOTIFIED_PT_rig_manager,
    DAMOTIFIED_PT_attachments,
    DAMOTIFIED_UL_animations,
    DAMOTIFIED_PT_animations,
    DAMOTIFIED_UL_animation_visibility,
    DAMOTIFIED_PT_animation_visibility,
    DAMOTIFIED_ShapeUVItem,
    DAMOTIFIED_UL_shape_uv,
    DAMOTIFIED_PT_shape_uv,
    DAMOTIFIED_PT_exporting,
)