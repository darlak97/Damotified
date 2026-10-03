import os
import difflib
import bpy
import random
import sys
import addon_utils
from ..debug import logger
from bpy.props import StringProperty, EnumProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper, ExportHelper

from ..importer import import_blockymodel, import_attachment_blockymodel
from ..exporter import export_blockyanim

def find_bone_collection_recursive(collection, name):
    """ Search for a specific bone collection by name."""
    if collection.name == name:
        return collection
        
    if hasattr(collection, "children"):
        for child in collection.children:
            found = find_bone_collection_recursive(child, name)
            if found:
                return found
                
    return None

def get_bone_collection(armature_data, name):
    """ Bone collection search."""
    if not hasattr(armature_data, "collections"):
        return None
    
    if name in armature_data.collections:
        return armature_data.collections[name]
        
    root_collections = [c for c in armature_data.collections if c.parent is None]
    
    for root_col in root_collections:
        found = find_bone_collection_recursive(root_col, name)
        if found:
            return found

    return None

# =========================================================
# Rig operators
# =========================================================

class DAMOTIFIED_OT_ToggleRigVisibility(Operator):
    """Toggles the viewport visibility of a specific rig collection or object."""
    bl_idname = "damotified.toggle_rig_visibility"
    bl_label = "Toggle Rig Visibility"
    bl_options = {'UNDO'}

    rig_name: StringProperty()

    def execute(self, context):
        if not self.rig_name:
            return {'CANCELLED'}
            
        rig_col = bpy.data.collections.get(self.rig_name)
        is_hidden = False
        
        if rig_col:
            rig_col.hide_viewport = not rig_col.hide_viewport
            is_hidden = rig_col.hide_viewport
        else:
            rig_obj = bpy.data.objects.get(self.rig_name)
            
            if rig_obj:
                rig_obj.hide_viewport = not rig_obj.hide_viewport
                is_hidden = rig_obj.hide_viewport
                
        if is_hidden:
            if context.scene.attachment_armature and context.scene.attachment_armature.name == self.rig_name:
                context.scene["last_attachment_armature"] = self.rig_name
                context.scene.attachment_armature = None
        else:
            last_rig = context.scene.get("last_attachment_armature")
            
            if last_rig == self.rig_name and not context.scene.attachment_armature:
                rig_obj = bpy.data.objects.get(self.rig_name)
                if rig_obj:
                    context.scene.attachment_armature = rig_obj
                
        return {'FINISHED'}


class DAMOTIFIED_OT_RemoveRig(Operator):
    """Removes armature, objects, and collections."""
    bl_idname = "damotified.remove_rig"
    bl_label = "Remove Rig"
    bl_description = "Remove Armature, Objects, Collections"
    bl_options = {'REGISTER', 'UNDO'}

    rig_name: bpy.props.StringProperty() # Property to exact name from UI list

    def execute(self, context):
        if not self.rig_name:
            return {'CANCELLED'}

        rig_obj = bpy.data.objects.get(self.rig_name)
        
        if not rig_obj or rig_obj.type != 'ARMATURE':
            self.report({'WARNING'}, "The selected object is not a rig or doesn't exist.")
            return {'CANCELLED'}

        rig_name = rig_obj.name
        rig_col = bpy.data.collections.get(rig_name)

        if rig_col:
            objs_to_delete = list(rig_col.all_objects)
            
            for obj in objs_to_delete:
                mesh_data = obj.data if obj.type == 'MESH' else None
                bpy.data.objects.remove(obj, do_unlink=True)
                
                if mesh_data and mesh_data.users == 0:
                    bpy.data.meshes.remove(mesh_data)
            
            bpy.data.collections.remove(rig_col, do_unlink=True)
        else:
            arm_data = rig_obj.data
            bpy.data.objects.remove(rig_obj, do_unlink=True)
            
            if arm_data and arm_data.users == 0:
                bpy.data.armatures.remove(arm_data)

        if context.scene.attachment_armature and context.scene.attachment_armature.name == rig_name:
            context.scene.attachment_armature = None

        self.report({'INFO'}, f"Rig '{rig_name}' removed successfully.")
        return {'FINISHED'}

# =========================================================
# Attachment operators
# =========================================================

class DAMOTIFIED_OT_ToggleAttachmentVisibility(Operator):
    """Toggles the visibility of an attachment collection."""
    bl_idname = "damotified.toggle_attachment_visibility"
    bl_label = "Toggle Attachment Visibility"
    bl_options = {'UNDO'}

    collection_name: StringProperty()

    def execute(self, context):
        armature_obj = context.scene.attachment_armature
        
        if not self.collection_name:
            return {'CANCELLED'}

        scene_coll = bpy.data.collections.get(self.collection_name)
        
        if not scene_coll:
            return {'CANCELLED'}

        scene_coll.hide_viewport = not scene_coll.hide_viewport
        should_be_visible = not scene_coll.hide_viewport

        if armature_obj and armature_obj.type == 'ARMATURE' and armature_obj.data:
            armature_data = armature_obj.data
            
            if should_be_visible:
                for parent_name in ("Main_Bones", "Attachments"):
                    parent_coll = get_bone_collection(armature_data, parent_name)
                    if parent_coll:
                        parent_coll.is_visible = True

            main_bone_coll = get_bone_collection(armature_data, self.collection_name)
            if main_bone_coll:
                main_bone_coll.is_visible = should_be_visible

            extra_bone_coll = get_bone_collection(armature_data, f"{self.collection_name}_Attachments")
            if extra_bone_coll:
                extra_bone_coll.is_visible = should_be_visible

            armature_data.update_tag()
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

        return {'FINISHED'}
        
class DAMOTIFIED_OT_AddAttachmentDummy(Operator):
    """ Operator for adding a new attachment logic."""
    bl_idname = "damotified.add_attachment"
    bl_label = "Add Attachment"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, "Add button pressed (Pending logic)")
        return {'FINISHED'}

class DAMOTIFIED_OT_RemoveAttachment(Operator):
    """Remove attachment objects, meshes, and bone collections."""
    bl_idname = "damotified.remove_attachment"
    bl_label = "Remove Attachment"
    bl_description = "Remove attachment Objects, Meshes, Bone collections"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        armature_obj = context.scene.attachment_armature
        
        if not armature_obj:
            self.report({'WARNING'}, "No armature selected.")
            return {'CANCELLED'}
            
        rig_collection = bpy.data.collections.get(armature_obj.name)
        attachments_parent = None
        
        if rig_collection:
            attachments_parent = next(
                (child for child in rig_collection.children if child.name.startswith("Attachments_Meshes")),
                None
            )
            
        if not attachments_parent:
            self.report({'WARNING'}, "Could not find any 'Attachments_Meshes' collection in the scene.")
            return {'CANCELLED'}
            
        children_cols = list(attachments_parent.children)
        index = context.scene.damotified_attachment_index
        
        if index < 0 or index >= len(children_cols):
            self.report({'WARNING'}, "Select an attachment from the list to remove.")
            return {'CANCELLED'}
            
        target_coll = children_cols[index]
        attachment_name = target_coll.name
        
        objs_to_delete = list(target_coll.all_objects)
        for obj in objs_to_delete:
            mesh_data = obj.data if obj.type == 'MESH' else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh_data and mesh_data.users == 0:
                bpy.data.meshes.remove(mesh_data)

        bpy.data.collections.remove(target_coll, do_unlink=True)
        
        armature_data = armature_obj.data
        target_bcolls = []

        bcoll_main = get_bone_collection(armature_data, attachment_name)
        if bcoll_main:
            target_bcolls.append(bcoll_main)

        bcoll_extra = get_bone_collection(armature_data, f"{attachment_name}_Attachments")
        if bcoll_extra:
            target_bcolls.append(bcoll_extra)

        bones_to_remove = set()
        
        for bcoll in target_bcolls:
            for b in bcoll.bones:
                bones_to_remove.add(b.name)
                
                if f"{b.name}_Config" in armature_data.bones:
                    bones_to_remove.add(f"{b.name}_Config")
                    
        if bones_to_remove:
            prev_mode = context.mode
            prev_active = context.view_layer.objects.active
            
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.select_all(action='DESELECT')
            armature_obj.select_set(True)
            context.view_layer.objects.active = armature_obj
            bpy.ops.object.mode_set(mode='EDIT')
            
            edit_bones = armature_data.edit_bones
            for b_name in bones_to_remove:
                eb = edit_bones.get(b_name)
                if eb:
                    edit_bones.remove(eb)
                    
            bpy.ops.object.mode_set(mode='OBJECT')
            
            if prev_active and prev_active.name in context.view_layer.objects:
                context.view_layer.objects.active = prev_active
                try:
                    if prev_mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode=prev_mode)
                except Exception:
                    pass
                    
        for bcoll in target_bcolls:
            armature_data.collections.remove(bcoll)
            
        new_len = len(attachments_parent.children)
        context.scene.damotified_attachment_index = max(0, min(index, new_len - 1))
        
        armature_data.update_tag()
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
                
        self.report({'INFO'}, f"Attachment '{attachment_name}' removed successfully.")
        return {'FINISHED'}

# =========================================================
# Importing utilities
# =========================================================

def get_import_types(self, context):
    """Returns available import target types on current scene."""
    items = [
        ('RIG', "Rig", "Import as main armature", 'ARMATURE_DATA', 0)
    ]
    
    if any(obj.type == 'ARMATURE' for obj in context.scene.objects):
        items.append(
            ('ATTACHMENT', "Attachment", "Import and link to armature", 'CON_KINEMATIC', 1)
        )
        
    return items

def get_image_files(self, context):
    """Scans the selected directory for image to assign."""
    items = [
        ("AUTO", "Automatic (Best Match)", "Searches for the image with the most similar name to the file"),
        ("NONE", "None (Ignore)", "Do not load texture automatically")
    ]
    
    if self.filepath:
        directory = os.path.dirname(self.filepath)
        
        if directory and os.path.isdir(directory):
            try:
                for f in os.listdir(directory):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tga', '.bmp')):
                        items.append((f, f, f"Use {f}"))
            except Exception:
                pass
                
    return items

def find_best_matching_image(directory, target_name):
    """Uses sequence matching to find the most similarly named texture file."""
    valid_extensions = ('.png', '.jpg', '.jpeg', '.tga', '.bmp')
    
    if not directory or not os.path.isdir(directory):
        return None
        
    try:
        images = [f for f in os.listdir(directory) if f.lower().endswith(valid_extensions)]
    except Exception:
        return None
        
    if not images:
        return None
        
    best_match = None
    best_score = -1.0
    target_name_lower = target_name.lower()
    
    for img in images:
        name_without_ext = os.path.splitext(img)[0].lower()
        score = difflib.SequenceMatcher(None, target_name_lower, name_without_ext).ratio()
        
        if score > best_score:
            best_score = score
            best_match = img
            
    return os.path.join(directory, best_match) if best_match else None

def update_texture_dropdown(self, context):
    """Clears the manual filepath"""
    if self.texture_filepath:
        self.texture_filepath = ""

class DAMOTIFIED_OT_ImportUnified(Operator, ImportHelper):
    """Imports a .blockymodel or .bbmodel file as a main rig or attachment."""
    bl_idname = "damotified.import_unified"
    bl_label = "Import Model"
    bl_description = "Import a .blockymodel or .bbmodel file."
    bl_options = {'REGISTER', 'UNDO'}
    
    filepath: StringProperty(subtype="FILE_PATH")
    
    filter_glob: StringProperty(
        default="*.blockymodel;*.bbmodel",
        options={'HIDDEN'},
    )
    
    import_type: EnumProperty( 
        name="Type",
        description="Select whether it is a Main Rig or an Attachment",
        items=get_import_types,
    )
    
    texture_filepath: StringProperty( 
        name="Manual Path",
        description="Enter the absolute texture path if it is in another location",
        default=""
    )
    
    texture_dropdown: EnumProperty( 
        name="Auto Texture",
        description="Select an option or detected image in the current folder",
        items=get_image_files,
        update=update_texture_dropdown # Clears the manual filepath when an auto texture option is selected
    )
    
    def invoke(self, context, event):
        return super().invoke(context, event)
        
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        
        box = layout.box()
        box.label(text="Import Options", icon='IMPORT')
        box.prop(self, "import_type")
        
        if self.import_type == 'ATTACHMENT':
            box.prop(context.scene, "attachment_armature", text="Target Rig", icon='OUTLINER_OB_ARMATURE')
            
            if not context.scene.attachment_armature:
                alert_row = box.row()
                alert_row.alert = True
                alert_row.label(text="Required: Select a Target Rig.", icon='ERROR')
                
        box_tex = layout.box()
        box_tex.label(text="Model Texture", icon='TEXTURE')
        box_tex.prop(self, "texture_filepath", text="Manual Path")
        box_tex.prop(self, "texture_dropdown", text="Auto-Detect")
        
    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "No file selected.")
            return {'CANCELLED'}
            
        file_name = os.path.splitext(os.path.basename(self.filepath))[0]
        directory = os.path.dirname(self.filepath)
        final_texture_path = ""
        manual_path = self.texture_filepath.strip()
        
        def get_dropdown_path():
            if self.texture_dropdown == "AUTO":
                found_path = find_best_matching_image(directory, file_name)
                return found_path if found_path else ""
            elif self.texture_dropdown == "NONE":
                return ""
            else:
                return os.path.join(directory, self.texture_dropdown)
                
        if manual_path:
            if os.path.exists(manual_path):
                final_texture_path = manual_path
            else:
                self.report({'WARNING'}, "Path file not found. Applying list option.")
                final_texture_path = get_dropdown_path()
        else:
            final_texture_path = get_dropdown_path()
            
        if self.import_type == 'RIG':
            return import_blockymodel(self.filepath, final_texture_path, context, self)
            
        elif self.import_type == 'ATTACHMENT':
            target_rig = context.scene.attachment_armature 
            
            if not target_rig:
                self.report({'ERROR'}, "No target armature selected in the import menu.")
                return {'CANCELLED'}
                
            rig_col = bpy.data.collections.get(target_rig.name)
            
            if rig_col and rig_col.hide_viewport:
                rig_col.hide_viewport = False
                
            if target_rig.hide_viewport:
                target_rig.hide_viewport = False
                
            return import_attachment_blockymodel(self.filepath, final_texture_path, context, target_rig, self)
     
# =========================================================     
# Animations
# =========================================================

def get_selected_armature_bones(context):
    """ Select bones list and the active bone."""
    armature = getattr(context.scene, "animation_armature", None)
    
    if not armature or armature.type != 'ARMATURE' or not armature.pose:
        return [], None
        
    selected_bones = []
    
    for p_bone in armature.pose.bones:
        is_selected = getattr(p_bone, 'select', getattr(p_bone.bone, 'select', False))
        if is_selected:
            selected_bones.append(p_bone)
            
    active_bone = context.active_pose_bone
    
    if not active_bone or active_bone.id_data != armature:
        active_bone = selected_bones[0] if selected_bones else None
        
    return selected_bones, active_bone

class DAMOTIFIED_OT_HideSelectedBones(Operator):
    """ Specified hide state to all selected bones."""
    bl_idname = "damotified.hide_selected_bones"
    bl_label = "Hide/Show Selected"
    bl_description = "Apply visibility to all selected bones"
    
    hide_state: bpy.props.BoolProperty(default=True)
    
    def execute(self, context):
        selected_bones, _ = get_selected_armature_bones(context)
        for p_bone in selected_bones:
            p_bone.hide = self.hide_state
        return {'FINISHED'}

def get_hide_keyframe_frames(action, bone_names):
    """Extracts all frames where the given bones have a hide keyframe."""
    if not action or not bone_names:
        return set()
        
    target_paths = {f'pose.bones["{name}"].hide' for name in bone_names}
    frames = set()
    
    if hasattr(action, 'layers'):
        for layer in action.layers:
            if hasattr(layer, 'strips'):
                for strip in layer.strips:
                    bags = []
                    if hasattr(strip, 'channelbag') and strip.channelbag:
                        bags.append(strip.channelbag)
                    if hasattr(strip, 'channelbags'):
                        bags.extend(list(strip.channelbags))
                    for bag in bags:
                        if hasattr(bag, 'fcurves'):
                            for fc in bag.fcurves:
                                if fc.data_path in target_paths:
                                    for kp in fc.keyframe_points:
                                        frames.add(round(kp.co[0]))
                                        
    if hasattr(action, 'fcurves'):
        for fc in list(action.fcurves):
            if fc.data_path in target_paths:
                for kp in fc.keyframe_points:
                    frames.add(round(kp.co[0]))
                    
    return frames

class DAMOTIFIED_OT_JumpHideKeyframe(Operator):
    """Jumps the timeline to next hide keyframe."""
    bl_idname = "damotified.jump_hide_keyframe"
    bl_label = "Jump to Hide Keyframe"
    bl_options = {'REGISTER', 'UNDO'}
    
    direction: bpy.props.EnumProperty(
        items=[
            ('PREV', "Previous", ""),
            ('NEXT', "Next", "")
        ]
    )
    
    @classmethod
    def poll(cls, context):
        scene = context.scene
        arm = scene.animation_armature
        actions = bpy.data.actions
        idx = scene.damotified_animation_index
        
        return (arm and arm.type == 'ARMATURE' and 
                context.mode == 'POSE' and 
                0 <= idx < len(actions))
                
    def execute(self, context):
        scene = context.scene
        actions = bpy.data.actions
        idx = scene.damotified_animation_index
        action = actions[idx]
        
        selected_bones, _ = get_selected_armature_bones(context) # Only selected bones
        
        if not selected_bones:
            return {'CANCELLED'}
            
        bone_names = [b.name for b in selected_bones]
        frames = get_hide_keyframe_frames(action, bone_names)
        
        if not frames:
            self.report({'WARNING'}, "No hide keyframes found for selected bones")
            return {'CANCELLED'}
            
        current_frame = scene.frame_current
        sorted_frames = sorted(list(frames))
        
        target_frame = None
        
        if self.direction == 'PREV':
            prev_frames = [f for f in sorted_frames if f < current_frame]
            if prev_frames:
                target_frame = prev_frames[-1]
        else:
            next_frames = [f for f in sorted_frames if f > current_frame]
            if next_frames:
                target_frame = next_frames[0]
                
        if target_frame is not None:
            scene.frame_set(target_frame)
            logger.debug(f"{{Visibility}} : Jumped to frame {target_frame}")
        else:
            self.report({'INFO'}, "No more keyframes in that direction")
            
        return {'FINISHED'}

class DAMOTIFIED_OT_ClearHideKeyframes(Operator):
    """Clears all hide channel keyframes for a specific bone."""
    bl_idname = "damotified.clear_hide_keyframes"
    bl_label = "Clear Hide Keyframes"
    bl_description = "Clear all hide channel keyframes for this specific bone"
    bl_options = {'REGISTER', 'UNDO'}

    bone_name: bpy.props.StringProperty() # Property to locate exact bone index

    @classmethod
    def poll(cls, context):
        scene = context.scene
        arm = scene.animation_armature
        actions = bpy.data.actions
        idx = scene.damotified_animation_index
        
        return (arm and arm.type == 'ARMATURE' and 
                context.mode == 'POSE' and 
                0 <= idx < len(actions))

    def execute(self, context):
        if not self.bone_name:
            return {'CANCELLED'}
            
        scene = context.scene
        armature = scene.animation_armature
        actions = bpy.data.actions
        idx = scene.damotified_animation_index
        action = actions[idx]
        
        target_path = f'pose.bones["{self.bone_name}"].hide' # Exact path Blender uses to hide bones
        removed_count = 0
        
        if hasattr(action, 'layers'):
            for layer in action.layers:
                if hasattr(layer, 'strips'):
                    for strip in layer.strips:
                        if hasattr(strip, 'channelbag') and strip.channelbag:
                            if hasattr(strip.channelbag, 'fcurves'):
                                for fc in list(strip.channelbag.fcurves):
                                    if fc.data_path == target_path:
                                        strip.channelbag.fcurves.remove(fc)
                                        removed_count += 1
                                        
                        if hasattr(strip, 'channelbags'):
                            for cb in strip.channelbags:
                                if hasattr(cb, 'fcurves'):
                                    for fc in list(cb.fcurves):
                                        if fc.data_path == target_path:
                                            cb.fcurves.remove(fc)
                                            removed_count += 1
                                            
        if hasattr(action, 'fcurves'):
            for fc in list(action.fcurves):
                if fc.data_path == target_path:
                    action.fcurves.remove(fc)
                    removed_count += 1

        if removed_count > 0:
            armature.update_tag()
            logger.debug(f"{{Visibility}} : Removed hide keyframes for '{self.bone_name}'")
            self.report({'INFO'}, f"Cleared hide keyframes for '{self.bone_name}'")
        else:
            self.report({'WARNING'}, f"No hide keyframes found for '{self.bone_name}'")
            
        return {'FINISHED'}

class DAMOTIFIED_OT_KeyframeSelectedBones(Operator):
    """Toggles hide keyframes for all selected bones."""
    bl_idname = "damotified.keyframe_selected_bones"
    bl_label = "Keyframe Selected"
    bl_description = "Toggle hide keyframes for all selected bones"
    
    def execute(self, context):
        selected_bones, _ = get_selected_armature_bones(context)
        
        for p_bone in selected_bones:
            try:
                removed = p_bone.keyframe_delete(data_path="hide")
                if not removed:
                    p_bone.keyframe_insert(data_path="hide")
            except Exception:
                p_bone.keyframe_insert(data_path="hide")
                
        return {'FINISHED'}
        
def get_mesh_from_bone(armature: bpy.types.Object, bone_name: str) -> bpy.types.Object:
    """Search for the main mesh by reading custom properties instead of constraints."""
    if not armature: 
        return None
    
    for obj in armature.children:
        if obj.type == 'MESH':
            is_linked_arm = (obj.damotified_linked_armature == armature)
            is_linked_bone = (obj.damotified_linked_bone == bone_name)
            is_main = obj.damotified_is_main_mesh
            
            if is_linked_arm and is_linked_bone and is_main:
                return obj
                
    # Fallback search across scene
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and obj.parent != armature:
            if obj.damotified_linked_armature == armature and obj.damotified_linked_bone == bone_name and obj.damotified_is_main_mesh:
                return obj
                
    return None

class DAMOTIFIED_OT_AddShapeUVBone(Operator):
    """Adds the selected bone to the Shape UV list."""
    bl_idname = "damotified.shape_uv_add"
    bl_label = "Add Selected Bone"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        if context.mode != 'POSE':
            return False
            
        _, active_bone = get_selected_armature_bones(context)
        return active_bone is not None
        
    def execute(self, context):
        scene = context.scene
        armature = scene.animation_armature
        _, active_bone = get_selected_armature_bones(context)
        
        if not active_bone:
            return {'CANCELLED'}
            
        for i, item in enumerate(scene.damotified_shape_uv_list):
            if item.name == active_bone.name:
                scene.damotified_shape_uv_index = i
                self.report({'INFO'}, f"Bone '{active_bone.name}' is already in the list")
                return {'CANCELLED'}
            
        item = scene.damotified_shape_uv_list.add()
        item.name = active_bone.name
        
        scene.damotified_shape_uv_index = len(scene.damotified_shape_uv_list) - 1
        
        obj = get_mesh_from_bone(armature, active_bone.name)
        scene.damotified_shape_uv_target = obj
        
        if not obj:
            self.report({'WARNING'}, f"No mesh detected for bone '{active_bone.name}'")
        else:
            props = getattr(obj, "uv_translate", None)
            
            if props:
                from ..shape_uv.core_uv_offset import (
                    find_object_image, _auto_steps, _last_px, as_pointer_safe, 
                    refresh_preview, setup_geonodes_drivers
                )
                
                if props.texture is None:
                    props.texture = find_object_image(obj)
                
                try: # calculate UV size for single face meshes
                    _auto_steps(obj)
                except Exception:
                    pass
                
                if "X shapeUvOffset" not in active_bone: 
                    active_bone["X shapeUvOffset"] = 0
                if "Y shapeUvOffset" not in active_bone: 
                    active_bone["Y shapeUvOffset"] = 0
                    
                setup_geonodes_drivers(obj, armature, active_bone.name)
                
                props.px_x = int(active_bone["X shapeUvOffset"])
                props.px_y = int(active_bone["Y shapeUvOffset"])

                ptr = as_pointer_safe(obj)
                _last_px[ptr] = (int(props.px_x), int(props.px_y))
                refresh_preview(obj, force=True)
            
            self.report({'INFO'}, f"Linked mesh '{obj.name}' to UV Shape")
            logger.debug(f"{{Shape UV}} : Linked mesh '{obj.name}' to bone '{active_bone.name}'")
            
        return {'FINISHED'}

class DAMOTIFIED_OT_RemoveShapeUVBone(Operator):
    """Removes the active bone from the Shape UV list."""
    bl_idname = "damotified.shape_uv_remove"
    bl_label = "Remove Shape UV Bone"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        idx = scene.damotified_shape_uv_index
        
        if 0 <= idx < len(scene.damotified_shape_uv_list):
            scene.damotified_shape_uv_list.remove(idx)
            
            new_idx = max(0, min(idx, len(scene.damotified_shape_uv_list) - 1))
            scene.damotified_shape_uv_index = new_idx
            
            if len(scene.damotified_shape_uv_list) == 0:
                scene.damotified_shape_uv_target = None
                
        return {'FINISHED'}
        
class DAMOTIFIED_OT_KeyframeShapeUV(Operator):
    """Insert a keyframe for the UV offset directly on the bone."""
    bl_idname = "damotified.keyframe_shape_uv"
    bl_label = "Keyframe UV Offset"
    bl_options = {'REGISTER', 'UNDO'}
    
    bone_name: bpy.props.StringProperty()
    
    @classmethod
    def poll(cls, context):
        scene = context.scene
        arm = scene.animation_armature
        return (arm and arm.type == 'ARMATURE' and context.mode == 'POSE')
        
    def execute(self, context):
        if not self.bone_name:
            return {'CANCELLED'}
            
        scene = context.scene
        armature = scene.animation_armature
        p_bone = armature.pose.bones.get(self.bone_name)
        
        if not p_bone:
            return {'CANCELLED'}
            
        target_mesh = get_mesh_from_bone(armature, self.bone_name)
        px_x, px_y = 0, 0
        
        if target_mesh:
            props = getattr(target_mesh, "uv_translate", None)
            if props:
                px_x = int(props.px_x)
                px_y = int(props.px_y)
            
        if "X shapeUvOffset" not in p_bone:
            p_bone["X shapeUvOffset"] = px_x
        if "Y shapeUvOffset" not in p_bone:
            p_bone["Y shapeUvOffset"] = px_y
            
        try:
            p_bone.keyframe_insert(data_path='["X shapeUvOffset"]')
            p_bone.keyframe_insert(data_path='["Y shapeUvOffset"]')
        except Exception as e:
            self.report({'WARNING'}, f"Could not keyframe bone: {e}")
            return {'CANCELLED'}
            
        action = armature.animation_data.action if armature.animation_data else None
        
        if action:
            current_frame = scene.frame_current
            path_x = f'pose.bones["{self.bone_name}"]["X shapeUvOffset"]'
            path_y = f'pose.bones["{self.bone_name}"]["Y shapeUvOffset"]'
            
            fcurves = []
            
            if hasattr(action, 'layers'):
                for layer in action.layers:
                    if hasattr(layer, 'strips'):
                        for strip in layer.strips:
                            if hasattr(strip, 'channelbag') and strip.channelbag:
                                if hasattr(strip.channelbag, 'fcurves'):
                                    fcurves.extend(list(strip.channelbag.fcurves))
                            if hasattr(strip, 'channelbags'):
                                for cb in strip.channelbags:
                                    if hasattr(cb, 'fcurves'):
                                        fcurves.extend(list(cb.fcurves))
                                        
            if hasattr(action, 'fcurves'):
                fcurves.extend(list(action.fcurves))
                
            for fc in fcurves:
                if fc.data_path in (path_x, path_y):
                    for kp in fc.keyframe_points:
                        if round(kp.co[0]) == round(current_frame):
                            kp.interpolation = 'CONSTANT'
                            
        logger.debug(f"{{Shape UV}} : Keyframed X={px_x} and Y={px_y} (CONSTANT) on '{self.bone_name}'")
        self.report({'INFO'}, f"Constant UV Keyframes added to '{self.bone_name}'")
        
        return {'FINISHED'}
        
# =========================================================
# Export operators
# =========================================================

class DAMOTIFIED_OT_ExportBlockyAnim(Operator, ExportHelper):
    """Handles the background export process for BlockyAnim."""
    bl_idname = "damotified.export_blockyanim"
    bl_label = "Export BlockyAnim"
    
    filename_ext = ".blockyanim" 
    
    filter_glob: StringProperty(
        default="*.blockyanim",
        options={'HIDDEN'},
        maxlen=255,
    )

    _timer = None
    _ticks = 0

    def invoke(self, context, event):
        action = context.scene.export_action
        
        if not action and context.active_object and getattr(context.active_object, "animation_data", None):
            action = context.active_object.animation_data.action
        
        if action:
            self.filepath = action.name + self.filename_ext
        
        return super().invoke(context, event)

    def execute(self, context):
        message_pool = [
            ("Exporting animation... Initializing 31 nodes. Please wait.", 56),
            ("Parsing vertex groups... Allocating 30 objects. Blender will stop responding.", 47),
            ("Processing UV maps... Task 65 in progress. Wait.", 45),
            ("Writing geometry Offset 59 has been reached. Please wait a few seconds...", 42),
            ("###| ERROR loading the message |###", 38),
            ("Applying modifiers... Buffer at 30 %. Blender is currently busy.", 36),
            ("Exporting armature | 38 % | Please be patient.", 28),
            ("Evaluating animation with a value of 74. Do click away.", 23),
            ("Compressing 67 HHhhYlleeE . . . Finishing up.", 18),
        ] # -
        
        messages = [item[0] for item in message_pool]
        weights = [item[1] for item in message_pool]
        
        random_message = random.choices(messages, weights=weights, k=1)[0]
        self.report({'WARNING'}, random_message)
        
        self._timer = context.window_manager.event_timer_add(0.1, window=context.window)
        context.window_manager.modal_handler_add(self)
        self._ticks = 0
        
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'TIMER':
            self._ticks += 1
            
            if self._ticks == 2:
                target_rig = context.scene.export_armature
                export_blockyanim(self.filepath, context, target_rig, self)
                context.window_manager.event_timer_remove(self._timer)
                return {'FINISHED'}
                
        return {'PASS_THROUGH'}

class DAMOTIFIED_OT_StartConfiguration(Operator):
    """Displays the initial welcome."""
    bl_idname = "damotified.start_configuration"
    bl_label = "START"
    bl_description = "Read the information for this alpha version before starting."
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=550)
        
    def draw(self, context):
        layout = self.layout
        
        addon_name = __package__.rsplit('.', 1)[0]
        version_str = "Beta"
        
        for mod in addon_utils.modules(): # Read extension metadata
            if mod.__name__ == addon_name:
                version_tuple = mod.bl_info.get("version", (0, 2, 0))
                version_str = ".".join(map(str, version_tuple))
                break
            
        box = layout.box()
        col = box.column(align=True)
        
        col.label(text=f"Damotified (Hytale Plugin) |v{version_str}|", icon='ERROR')
        col.label(text="|Basic stable version of Damotified.|")
        col.label(text="This plugin was designed to import, animate, and export animations for Hytale")
        col.label(text="following the rules and restrictions of the game animations adapted to Blender.")
        
        col.label(text="")
        col.label(text="This project has been in development for a long time, and there are still more tools to be added.")
        col.label(text="Any comments or bugs can be reported on the Blender page and repository.")
        
        col.label(text="")
        col.label(text="Want to know more? Learn more by visiting the repository page.")
        
        layout.separator()
        
        row = box.row()
        row.alignment = 'LEFT'
        row.label(text="Github:")
        op = row.operator("wm.url_open", text="Damotified", icon='URL', emboss=False)
        op.url = "https://github.com/darlak97/Damotified"
        
    def execute(self, context):
        # Sets a session flag Blender
        context.scene["damotified_is_configured"] = True
        return {'FINISHED'}

def menu_func_import(self, context):
    """ Damotified importer to Blender | File > Import menu."""
    op = self.layout.operator("damotified.import_unified", text="Hytale Model (.blockymodel, .bbmodel)", icon='CUBE')
    op.import_type = 'RIG'

classes = (
    DAMOTIFIED_OT_ToggleRigVisibility,
    DAMOTIFIED_OT_RemoveRig,
    DAMOTIFIED_OT_ToggleAttachmentVisibility,
    DAMOTIFIED_OT_AddAttachmentDummy,
    DAMOTIFIED_OT_RemoveAttachment,
    DAMOTIFIED_OT_ImportUnified,
    DAMOTIFIED_OT_HideSelectedBones,
    DAMOTIFIED_OT_JumpHideKeyframe,
    DAMOTIFIED_OT_ClearHideKeyframes,
    DAMOTIFIED_OT_KeyframeSelectedBones,
    DAMOTIFIED_OT_AddShapeUVBone,
    DAMOTIFIED_OT_RemoveShapeUVBone,
    DAMOTIFIED_OT_KeyframeShapeUV,
    DAMOTIFIED_OT_ExportBlockyAnim,
    DAMOTIFIED_OT_StartConfiguration
)