bl_info = {
    "name": "Damotified",
    "description": "Damotified tool for Hytale animations",
    "author": "darlak97",
    "version": (0, 1),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > Damotified",
    "warning": "This plugin aims to provide Blockbench compatibility for Hytale.",
    "wiki_url": "https://github.com/",
    "tracker_url": "https://github.com/",
    "category": "Animation",
}

import bpy

from bpy.types import Operator, Panel

from .Panels import DAMOTIFIED_PT_rig_manager, DAMOTIFIED_PT_attachments, DAMOTIFIED_UL_attachments, DAMOTIFIED_UL_rigs, DAMOTIFIED_DummyItem

from .Operators import DAMOTIFIED_OT_ImportUnified, DAMOTIFIED_OT_ToggleAttachmentVisibility, DAMOTIFIED_OT_AddAttachmentDummy
from .Operators import DAMOTIFIED_OT_RemoveAttachment, DAMOTIFIED_OT_ToggleRigVisibility, DAMOTIFIED_OT_RemoveRig

# ==============================================================================
# Initial Panel
# ==============================================================================

class DAMOTIFIED_PT_initial_panel(Panel):
    
    bl_label = "Damotified"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    
    @classmethod
    def poll(cls, context):
        return not context.scene.damotified_configured
        
    def draw(self, context):
        layout = self.layout
        box = layout.box()
        row = box.row()
        
        row.label(text="Caution", icon='ERROR')
        box.label(text="Project in development.")
        layout.separator()
        layout.operator("damotified.start_configuration", icon='PREFERENCES')

# ==============================================================================
# Initialization Operator
# ==============================================================================

class DAMOTIFIED_OT_StartConfiguration(Operator):
    bl_idname = "damotified.start_configuration"
    bl_label = "START"
    bl_description = "Read the information for this alpha version before starting."

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=550)

    # Introductory text and version/development warning for the Add-on.
    def draw(self, context):
        layout = self.layout

        box = layout.box()
        col = box.column(align=True)
        
        col.label(text="Damotified (Hytale Plugin) |v0.1|", icon='ERROR')
        col.label(text="Currently, this first version only has the model import tool.")
        
        col.label(text="The plan is to add rig configuration and animation export for Hytale.")
        col.label(text="This project has been in the planning stages for months and will take some time to complete.")
        
        col.label(text="")
        col.label(text="If you’d like to support the project, check out my X profile")

        layout.separator()

        row = box.row()
        row.alignment = 'LEFT'
        row.label(text="X:")
        op = row.operator("wm.url_open", text="x.com/darlak97", icon='URL', emboss=False)
        op.url = "https://x.com/darlak97"

    def execute(self, context):
    # Set scene configuration | Discarded
        
        #context.scene.render.fps = 60
        #context.scene.unit_settings.scale_length = 64
        
        context.scene.damotified_configured = True
        return {'FINISHED'}

# ==============================================================================
# Registration
# ==============================================================================

classes = (
    DAMOTIFIED_PT_initial_panel,
    DAMOTIFIED_PT_rig_manager,
    DAMOTIFIED_PT_attachments,
    
    DAMOTIFIED_DummyItem, # Helper
    DAMOTIFIED_UL_attachments, # Attachment Scene
    DAMOTIFIED_UL_rigs, # Rig Scene
    
    DAMOTIFIED_OT_ToggleAttachmentVisibility,
    DAMOTIFIED_OT_AddAttachmentDummy,
    DAMOTIFIED_OT_RemoveAttachment,
    DAMOTIFIED_OT_ToggleRigVisibility,
    DAMOTIFIED_OT_RemoveRig,
    DAMOTIFIED_OT_StartConfiguration,
    DAMOTIFIED_OT_ImportUnified,
)

# --- Custom Import Menu Function ---
def menu_func_import(self, context):
    """Blender's native Importer (File > Import) menu."""
    op = self.layout.operator("damotified.import_unified", text="Hytale Model (.blockymodel, .bbmodel)", icon='CUBE')
    op.import_type = 'RIG'

def poll_armatures_only(self, object):
    # Armature Filter
    return object.type == 'ARMATURE'

def register():
    """Blender register Classes."""
    # 0. Register all classes first
    for cls in classes:
        bpy.utils.register_class(cls)

    # 1. Blender Importer category
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    # 2. Assign properties to Scene
     # DAMOTIFIED_PT_rig_manager
    bpy.types.Scene.damotified_configured = bpy.props.BoolProperty(
        name="Damotified Configured",
        default=False
    )
     # DAMOTIFIED_PT_rig_manager
    bpy.types.Scene.damotified_rig_index = bpy.props.IntProperty(
        name="Rig Index",
        default=0
    )
     # DAMOTIFIED_PT_rig_manager
    bpy.types.Scene.damotified_empty_collection = bpy.props.CollectionProperty(
        type=DAMOTIFIED_DummyItem
    )
     # DAMOTIFIED_PT_attachments
    bpy.types.Scene.attachment_armature = bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Armature",
        description="Select the main armature to which the attachment will be linked",
        poll=poll_armatures_only
    )
     # DAMOTIFIED_PT_attachments
    bpy.types.Scene.damotified_attachment_index = bpy.props.IntProperty(
        name="Attachment Index",
        default=0
    )

def unregister():
    """Blender unregister Classes."""
    # Remove from Blender importer
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

    # Remove Scene properties
    del bpy.types.Scene.damotified_configured
    del bpy.types.Scene.damotified_rig_index
    del bpy.types.Scene.damotified_empty_collection
    del bpy.types.Scene.attachment_armature
    del bpy.types.Scene.damotified_attachment_index
    
    # Unregister classes in reverse order
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)