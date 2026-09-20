import bpy
from bpy.types import Panel, UIList, PropertyGroup

# Helper class for the custom UIList
class DAMOTIFIED_DummyItem(PropertyGroup):
    pass

class DAMOTIFIED_UL_rigs(UIList):
    # Custom UIList for the display Armature objects (Rigs)
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
            layout.label(text=item.name, icon='OUTLINER_OB_ARMATURE')
            
            # Check visibility of the collection
            rig_col = bpy.data.collections.get(item.name)
            is_hidden = rig_col.hide_viewport if rig_col else item.hide_viewport
            
            icon_eye = 'HIDE_ON' if is_hidden else 'HIDE_OFF'
            
            op = layout.operator(
                "damotified.toggle_rig_visibility",
                text="",
                icon=icon_eye,
                emboss=False
            )
            op.rig_name = item.name
            
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OUTLINER_OB_ARMATURE')

class DAMOTIFIED_UL_attachments(UIList):
    # Custom UIList to display the attachment collections
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if hasattr(item, "name"):
                layout.label(text=item.name, icon='OUTLINER_COLLECTION')
                if hasattr(item, "hide_viewport"):
                    icon_eye = ('HIDE_OFF', 'HIDE_ON')[item.hide_viewport]
                    
                    # Visibility button
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
    bl_idname = "DAMOTIFIED_PT_rig_manager"
    bl_label = "Rig Manager"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    
    @classmethod
    def poll(cls, context):
        return context.scene.damotified_configured
        
    def draw(self, context):
        layout = self.layout
        
        # Rig manager (template_list)
        row = layout.row()
        # Iterates over context.scene.objects, filtering in UL class
        row.template_list(
            "DAMOTIFIED_UL_rigs",
            "damotified_rigs_list",
            context.scene,
            "objects",
            context.scene,
            "damotified_rig_index",
            rows=3
        )

        # Side buttons column (+ / -)
        col_btn = row.column(align=True)
        
        add_op = col_btn.operator("damotified.import_unified", text="", icon='ADD')
        add_op.import_type = 'RIG'
        
        sub_col = col_btn.column(align=True)
        has_rigs = any(obj.type == 'ARMATURE' for obj in context.scene.objects)
        sub_col.enabled = has_rigs
        sub_col.operator("damotified.remove_rig", text="", icon='REMOVE')


class DAMOTIFIED_PT_attachments(Panel):
    bl_idname = "DAMOTIFIED_PT_attachments"
    bl_parent_id = "DAMOTIFIED_PT_rig_manager"
    bl_label = "Attachments"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Damotified"
    bl_options = {'DEFAULT_CLOSED'}
    
    def draw(self, context):
        layout = self.layout
        
        # Object
        layout.prop(context.scene, "attachment_armature", text="Armature", icon='OUTLINER_OB_ARMATURE')

        armature_obj = context.scene.attachment_armature
        
        dataptr = context.scene
        propname = "damotified_empty_collection"
        
        if armature_obj: # Armatures
            rig_collection = bpy.data.collections.get(armature_obj.name)
            if rig_collection:
                # Look for the first collection with "Attachments_Meshes"
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
        
        # Side buttons (+ / -)
        col_btn = row.column(align=True)
        col_btn.enabled = armature_obj is not None
        
        add_op = col_btn.operator("damotified.import_unified", text="", icon='ADD')
        add_op.import_type = 'ATTACHMENT'
        
        sub_col = col_btn.column(align=True)
        has_items = False
        if armature_obj: # Button - | Attachment mesh
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