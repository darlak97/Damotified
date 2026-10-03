"""/"""
bl_info = {
    "name": "Damotified",
    "description": "Damotified tool for Hytale animations",
    "author": "darlak97",
    "version": (0, 2, 0),
    "blender": (5, 0, 1),
    "location": "View3D > Sidebar > Damotified",
    "warning": "This plugin aims to provide Blockbench compatibility for Hytale.",
    "wiki_url": "https://github.com/darlak97/Damotified/issues",
    "tracker_url": "https://github.com/darlak97/Damotified/issues/new?template=error_report.md",
    "category": "Animation",
}

# Import
from . import debug
from . import ui
from . import shape_uv
from . import importer
from . import exporter

# ==============================================================================
# MAIN REGISTRATION
# ==============================================================================

def register():
    debug.register()
    importer.register()
    exporter.register()
    shape_uv.register()
    ui.register()

def unregister():
    ui.unregister()
    shape_uv.unregister()
    exporter.unregister()
    importer.unregister()
    debug.unregister()

if __name__ == "__main__":
    register()