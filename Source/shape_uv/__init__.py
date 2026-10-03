import bpy
from bpy.props import PointerProperty

from .core_uv_offset import init_globals, clear_globals
from .main_uv_offset import classes, UVTX_PG_settings

# Registration

def register():
    """Initializes globals and registers all classes and properties for the UV tool."""
    init_globals()
    
    for cls in classes:
        bpy.utils.register_class(cls)
        
    bpy.types.Object.uv_translate = PointerProperty(type=UVTX_PG_settings)

def unregister():
    """Cleans up memory, globals, and unregisters the UV tool classes."""
    del bpy.types.Object.uv_translate
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
        
    clear_globals()

    try: # clean preview generated images
        for img in list(bpy.data.images):
            if img.name.startswith("UVTX_Preview_"):
                bpy.data.images.remove(img)
    except Exception:
        pass