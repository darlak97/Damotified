import bpy
import logging
from ..debug import logger

def update_debug_mode(self, context):
    """ Changes the global logger level when the checkbox is toggled."""
    if self.debug_mode:
        logger.setLevel(logging.DEBUG)
        logger.debug("{Preferences} : Debug mode ENABLED")
    else:
        logger.setLevel(logging.WARNING)
        print("[Damotified] {Preferences} : Debug mode DISABLED")

class DAMOTIFIED_AddonPreferences(bpy.types.AddonPreferences):
    """ Global addon preferences window."""
    bl_idname = __package__.rsplit('.', 1)[0] # Prevent path resolution issues

    is_configured: bpy.props.BoolProperty(
        name="Is Configured",
        default=False
    )
    
    debug_mode: bpy.props.BoolProperty(
        name="Enable Debug Mode",
        description="Show developer debug messages in the system console",
        default=False,
        update=update_debug_mode
    )

    def draw(self, context):
        layout = self.layout
        
        box = layout.box()
        box.label(text="Damotified Global Settings", icon='PREFERENCES')
        
        row = box.row()
        row.prop(self, "is_configured", text="Hide Welcome Panel")
        row.prop(self, "debug_mode", text="Enable Debug Logging", icon='CONSOLE')


classes = (DAMOTIFIED_AddonPreferences,)