import bpy
from bpy.props import StringProperty, BoolProperty, PointerProperty
from .main_importer import import_blockymodel, import_attachment_blockymodel

# registration

def register():
    # Registers custom object to track mesh and bone relationships
    bpy.types.Object.damotified_linked_armature = PointerProperty(
        type=bpy.types.Object,
        name="Linked Armature"
    )
    bpy.types.Object.damotified_linked_bone = StringProperty(
        name="Linked Bone"
    )
    bpy.types.Object.damotified_is_main_mesh = BoolProperty(
        name="Is Main Mesh",
        default=False
    )

def unregister():
    del bpy.types.Object.damotified_linked_armature
    del bpy.types.Object.damotified_linked_bone
    del bpy.types.Object.damotified_is_main_mesh