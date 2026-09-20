import os
import difflib
import bpy
from bpy.props import StringProperty, EnumProperty, PointerProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

# Import the main functions from the logic file
from .Main_Importer import import_blockymodel
from .Main_Importer import import_attachment_blockymodel

def find_bone_collection_recursive(collection, name):
    """Recursively searches for a Bone Collection by name navigating its children"""
    if collection.name == name:
        return collection
    if hasattr(collection, "children"):
        for child in collection.children:
            found = find_bone_collection_recursive(child, name)
            if found:
                return found
    return None

def get_bone_collection(armature_data, name):
    """Gets a Bone Collection searching in the root and recursively"""
    if not hasattr(armature_data, "collections"):
        return None
    
    # 1. Attempt direct search
    if name in armature_data.collections:
        return armature_data.collections[name]

    # 2. If nested in the hierarchy, search recursively from root collections
    root_collections = [c for c in armature_data.collections if c.parent is None]
    for root_col in root_collections:
        found = find_bone_collection_recursive(root_col, name)
        if found:
            return found

    return None

# ==============================================================================
# RIG OPERATORS
# ==============================================================================

class DAMOTIFIED_OT_ToggleRigVisibility(Operator):
    """Toggles the visibility of the selected Rig collection"""
    bl_idname = "damotified.toggle_rig_visibility"
    bl_label = "Toggle Rig Visibility"
    bl_options = {'UNDO'}

    rig_name: bpy.props.StringProperty()

    def execute(self, context):
        if not self.rig_name:
            return {'CANCELLED'}
            
        rig_col = bpy.data.collections.get(self.rig_name)
        is_hidden = False
        
        if rig_col:
            # Hide the entire collection
            rig_col.hide_viewport = not rig_col.hide_viewport
            is_hidden = rig_col.hide_viewport
        else:
            # Fallback to hide armature
            rig_obj = bpy.data.objects.get(self.rig_name)
            if rig_obj:
                rig_obj.hide_viewport = not rig_obj.hide_viewport
                is_hidden = rig_obj.hide_viewport
                
        # For attachments
        if is_hidden:
            # Save rig
            if context.scene.attachment_armature and context.scene.attachment_armature.name == self.rig_name:
                context.scene["last_attachment_armature"] = self.rig_name
                context.scene.attachment_armature = None
        else:
            # Check the last one selected.
            last_rig = context.scene.get("last_attachment_armature")
            if last_rig == self.rig_name and not context.scene.attachment_armature:
                
                rig_obj = bpy.data.objects.get(self.rig_name)
                if rig_obj:
                    context.scene.attachment_armature = rig_obj
                
        return {'FINISHED'}


class DAMOTIFIED_OT_RemoveRig(Operator):
    """Removes the selected rig, its meshes, and its collection"""
    bl_idname = "damotified.remove_rig"
    bl_label = "Remove Rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        index = context.scene.damotified_rig_index
        
        # Guard check if index is valid inside the objects list
        if index < 0 or index >= len(context.scene.objects):
            self.report({'WARNING'}, "Select a valid rig from the list to remove.")
            return {'CANCELLED'}

        rig_obj = context.scene.objects[index]
        
        # Verify the selected index is actually an Armature
        if rig_obj.type != 'ARMATURE':
            self.report({'WARNING'}, "The selected object is not a rig.")
            return {'CANCELLED'}

        rig_name = rig_obj.name
        rig_col = bpy.data.collections.get(rig_name)

        # Remove everything inside its linked collection
        if rig_col:
            objs_to_delete = list(rig_col.all_objects)
            for obj in objs_to_delete:
                mesh_data = obj.data if obj.type == 'MESH' else None
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh_data and mesh_data.users == 0:
                    bpy.data.meshes.remove(mesh_data)
            
            # Remove the collection itself
            bpy.data.collections.remove(rig_col, do_unlink=True)
        else:
            # Fallback: Just remove the armature object and its data
            arm_data = rig_obj.data
            bpy.data.objects.remove(rig_obj, do_unlink=True)
            if arm_data and arm_data.users == 0:
                bpy.data.armatures.remove(arm_data)

        # Refresh UI selection if target armature was the removed one
        if context.scene.attachment_armature and context.scene.attachment_armature.name == rig_name:
            context.scene.attachment_armature = None

        self.report({'INFO'}, f"Rig '{rig_name}' removed successfully.")
        return {'FINISHED'}


# ==============================================================================
# ATTACHMENT OPERATORS
# ==============================================================================

class DAMOTIFIED_OT_ToggleAttachmentVisibility(Operator):
    """Toggles the visibility of the scene collection and rig Bone Collections"""
    bl_idname = "damotified.toggle_attachment_visibility"
    bl_label = "Toggle Attachment Visibility"
    bl_options = {'UNDO'}

    collection_name: bpy.props.StringProperty()

    def execute(self, context):
        armature_obj = context.scene.attachment_armature
        if not self.collection_name:
            return {'CANCELLED'}

        # Scene collection and toggle visibility
        scene_coll = bpy.data.collections.get(self.collection_name)
        if not scene_coll:
            return {'CANCELLED'}

        scene_coll.hide_viewport = not scene_coll.hide_viewport
        should_be_visible = not scene_coll.hide_viewport

        # Update the Rig's Bone Collections
        if armature_obj and armature_obj.type == 'ARMATURE' and armature_obj.data:
            armature_data = armature_obj.data
            
            if should_be_visible:
                for parent_name in ("Main_Bones", "Attachments"):
                    parent_coll = get_bone_collection(armature_data, parent_name)
                    if parent_coll:
                        parent_coll.is_visible = True

            # Find the main Bone Collection (Main_Bones -> Attachments -> [Name])
            main_bone_coll = get_bone_collection(armature_data, self.collection_name)
            if main_bone_coll:
                main_bone_coll.is_visible = should_be_visible

            # nubs/attachments Bone Collection ([Name]_Attachments)
            extra_bone_coll = get_bone_collection(armature_data, f"{self.collection_name}_Attachments")
            if extra_bone_coll:
                extra_bone_coll.is_visible = should_be_visible

            # Refresh the 3D view
            armature_data.update_tag()
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

        return {'FINISHED'}
        
class DAMOTIFIED_OT_AddAttachmentDummy(Operator):
    bl_idname = "damotified.add_attachment"
    bl_label = "Add Attachment"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, "Add button pressed (Pending logic)")
        return {'FINISHED'}


class DAMOTIFIED_OT_RemoveAttachment(Operator):
    """Removes the selected attachment, its objects, meshes, and bones collections"""
    bl_idname = "damotified.remove_attachment"
    bl_label = "Remove Attachment"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        armature_obj = context.scene.attachment_armature
        if not armature_obj:
            self.report({'WARNING'}, "No armature selected.")
            return {'CANCELLED'}
            
        # Collection Scene
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
        
        # Validate selected index
        if index < 0 or index >= len(children_cols):
            self.report({'WARNING'}, "Select an attachment from the list to remove.")
            return {'CANCELLED'}
            
        target_coll = children_cols[index]
        attachment_name = target_coll.name
        
        # REMOVE OBJECTS AND MESHES FROM THE SCENE COLLECTION
        objs_to_delete = list(target_coll.all_objects)
        for obj in objs_to_delete:
            mesh_data = obj.data if obj.type == 'MESH' else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh_data and mesh_data.users == 0:
                bpy.data.meshes.remove(mesh_data)

        # Remove the attachment
        bpy.data.collections.remove(target_coll, do_unlink=True)
        
        # Get bone collection
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
                # Get configuration bone
                if f"{b.name}_Config" in armature_data.bones:
                    bones_to_remove.add(f"{b.name}_Config")
                    
        # REMOVE BONES IN EDIT MODE
        if bones_to_remove:
            prev_mode = context.mode
            prev_active = context.view_layer.objects.active

            # Select the armature and enter EDIT mode
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

            # Return to previous mode
            bpy.ops.object.mode_set(mode='OBJECT')
            if prev_active and prev_active.name in context.view_layer.objects:
                context.view_layer.objects.active = prev_active
                try:
                    if prev_mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode=prev_mode)
                except Exception:
                    pass
                    
        # REMOVE BONE COLLECTIONS
        for bcoll in target_bcolls:
            armature_data.collections.remove(bcoll)

        # Adjust UI list index after removal
        new_len = len(attachments_parent.children)
        context.scene.damotified_attachment_index = max(0, min(index, new_len - 1))
        
        # Refresh Viewport
        armature_data.update_tag()
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        self.report({'INFO'}, f"Attachment '{attachment_name}' removed successfully.")
        return {'FINISHED'}

# ==============================================================================
# IMPORTING UTILITIES
# ==============================================================================

def get_import_types(self, context):
    items = [
        ('RIG', "Rig", "Import as main armature", 'ARMATURE_DATA', 0)
    ]
    
    # Checks if there is at least one (ARMATURE)
    if any(obj.type == 'ARMATURE' for obj in context.scene.objects):
        items.append(
            ('ATTACHMENT', "Attachment", "Import and link to armature", 'CON_KINEMATIC', 1)
        )
        
    return items

def get_image_files(self, context):
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
    if self.texture_filepath:
        self.texture_filepath = ""

class DAMOTIFIED_OT_ImportUnified(Operator, ImportHelper):
    bl_idname = "damotified.import_unified"
    bl_label = "Import Model"
    bl_description = "Imports a Blockymodel file (Main Rig or Attachment)"
    bl_options = {'REGISTER', 'UNDO'}
    
    filepath: StringProperty(subtype="FILE_PATH")
    
    filter_glob: StringProperty(
        default="*.blockymodel;*.bbmodel",
        options={'HIDDEN'},
    )
    
    import_type: EnumProperty( # Type archive
        name="Type",
        description="Select whether it is a Main Rig or an Attachment",
        items=get_import_types,
    )
    
    texture_filepath: StringProperty( # Path
        name="Manual Path",
        description="Enter the absolute texture path if it is in another location",
        default=""
    )
    
    texture_dropdown: EnumProperty( # Texture
        name="Auto Texture",
        description="Select an option or detected image in the current folder",
        items=get_image_files,
        update=update_texture_dropdown
    )
    
    def invoke(self, context, event):
        return super().invoke(context, event)
        
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        
        box = layout.box()
        box.label(text="Import Options", icon='IMPORT')
        box.prop(self, "import_type")
        
        # Read and draw directly the var
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
                
            # Check Rig list
            rig_col = bpy.data.collections.get(target_rig.name)
            if rig_col and rig_col.hide_viewport:
                rig_col.hide_viewport = False
                
            if target_rig.hide_viewport:
                target_rig.hide_viewport = False
                
            return import_attachment_blockymodel(self.filepath, final_texture_path, context, target_rig, self)