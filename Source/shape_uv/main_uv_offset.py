import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from .core_uv_offset import (
    BASE_LAYER, _pv_rev, _last_px, _pv_icon, _pv_state, np,
    init_globals, clear_globals, find_object_image, _redraw,
    as_pointer_safe, fit_scale,
    _preview_state, refresh_preview, _release_preview,
    refresh_preview_if_editing, _on_uv_offset_update, 
    _on_pv_zoom_update, _auto_steps,
    is_preview_throttled, _request_preview_throttled
)
# =========================================================
# Properties
# =========================================================

class UVTX_PG_settings(PropertyGroup):
    """ Custom properties for the UV translation tool per object."""
    texture: PointerProperty(
        name="Texture",
        type=bpy.types.Image,
        description="Texture confirmed to edit this UV",
    )
    preview_image: PointerProperty(
        name="Preview Image",
        type=bpy.types.Image,
        description="Internal image with the texture and drawn UVs",
        options={'HIDDEN'},
    )
    px_x: IntProperty(
        name="X Translation",
        description="Horizontal UV offset in texture PIXELS. 0 = original position",
        default=0, min=-2000, max=2000, step=1,
        subtype='PIXEL',
        update=_on_uv_offset_update,
    )
    px_y: IntProperty(
        name="Y Translation",
        description="Vertical UV offset in texture PIXELS. 0 = original position",
        default=0, min=-2000, max=2000, step=1,
        subtype='PIXEL',
        update=_on_uv_offset_update,
    )
    pv_zoom: IntProperty(
        name="Preview Zoom",
        description="Zoom level of the preview",
        default=1, min=1, max=16,
        update=_on_pv_zoom_update,
    )
    step_x: IntProperty(
        name="Step X",
        description="Pixels advanced per arrow click in X Translation",
        default=32, min=0, max=100, step=1,
        subtype='PIXEL',
    )
    step_y: IntProperty(
        name="Step Y",
        description="Pixels advanced per arrow click in Y Translation",
        default=32, min=0, max=100, step=1,
        subtype='PIXEL',
    )

# =========================================================
# Operators
# =========================================================

class UVTX_OT_translate_step(Operator):
    """ Applies a step increment to the UV translation properties."""
    bl_idname = "uvtx.translate_step"
    bl_label = "Step Translate"
    bl_description = "Apply the Step increment to the translation"
    bl_options = {'REGISTER', 'UNDO'}

    axis: StringProperty()
    direction: IntProperty(default=1)

    @classmethod
    def poll(cls, context):
        ob = getattr(context.scene, "damotified_shape_uv_target", None)
        return (ob is not None and ob.type == 'MESH')

    def execute(self, context):
        ob = context.scene.damotified_shape_uv_target
        props = ob.uv_translate
        
        arm = context.scene.animation_armature
        idx = context.scene.damotified_shape_uv_index
        lst = context.scene.damotified_shape_uv_list
        p_bone = arm.pose.bones.get(lst[idx].name) if arm and 0 <= idx < len(lst) else None
        
        # Synchronize UI click with bone property
        if p_bone and "X shapeUvOffset" in p_bone:
            if self.axis == 'X':
                p_bone["X shapeUvOffset"] += props.step_x * self.direction
            elif self.axis == 'Y':
                p_bone["Y shapeUvOffset"] += props.step_y * self.direction
        else:
            # Fallback to mesh properties
            if self.axis == 'X':
                props.px_x += props.step_x * self.direction
            elif self.axis == 'Y':
                props.px_y += props.step_y * self.direction
                
        if arm:
            arm.update_tag()
            
        if ob and ob.active_material and ob.active_material.use_nodes:
            ob.active_material.node_tree.update_tag()
            
        _request_preview_throttled(ob)
        _redraw(context)
        
        return {'FINISHED'}

class UVTX_OT_zoom_step(Operator):
    """ Increases or decreases the preview zoom level."""
    bl_idname = "uvtx.zoom_step"
    bl_label = "Step Zoom"
    bl_description = "Increase or decrease the preview zoom level"
    bl_options = {'REGISTER', 'UNDO'}

    step: IntProperty(default=1)

    @classmethod
    def poll(cls, context):
        ob = getattr(context.scene, "damotified_shape_uv_target", None)
        return (ob is not None and ob.type == 'MESH')

    def execute(self, context):
        ob = context.scene.damotified_shape_uv_target
        props = ob.uv_translate
        
        props.pv_zoom = max(1, min(16, props.pv_zoom + self.step))
        
        return {'FINISHED'}

class UVTX_OT_reset(Operator):
    """ Reset the UV translation offsets."""
    bl_idname = "uvtx.reset_offsets"
    bl_label = "Reset UVs (0 px, 0 px)"
    bl_description = "Reset position to the Original UV."
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        ob = getattr(context.scene, "damotified_shape_uv_target", None)
        return (ob is not None and ob.type == 'MESH')

    def execute(self, context):
        ob = context.scene.damotified_shape_uv_target
        props = ob.uv_translate
        
        arm = context.scene.animation_armature
        idx = context.scene.damotified_shape_uv_index
        lst = context.scene.damotified_shape_uv_list
        p_bone = arm.pose.bones.get(lst[idx].name) if arm and 0 <= idx < len(lst) else None
        
        if p_bone:
            p_bone["X shapeUvOffset"] = 0
            p_bone["Y shapeUvOffset"] = 0
            
        props.px_x = 0   
        props.px_y = 0
        
        if arm:
            arm.update_tag()
            
        if ob and ob.active_material and ob.active_material.use_nodes:
            ob.active_material.node_tree.update_tag()
            
        _request_preview_throttled(ob)
        _redraw(context)
        
        self.report({'INFO'}, "UVs restored to 0")
        return {'FINISHED'}

class UVTX_OT_auto_step(Operator):
    """ Detect and sets the step size based on UV boundaries."""
    bl_idname = "uvtx.auto_step"
    bl_label = "Auto-Detect UV Size"
    bl_description = "Automatically set Step sizes to match the UV dimensions"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = getattr(context.scene, "damotified_shape_uv_target", None)
        return (ob is not None and ob.type == 'MESH' and len(ob.data.polygons) == 1)

    def execute(self, context):
        ob = context.scene.damotified_shape_uv_target
        
        from .core_uv_offset import _auto_steps
        _auto_steps(ob)
        
        self.report({'INFO'}, f"Steps adjusted to: {ob.uv_translate.step_x}x{ob.uv_translate.step_y} px")
        return {'FINISHED'}

# =========================================================
# UI Panel Draw Logic
# =========================================================

def draw_uvtx_panel(panel, context):
    """Draws the Shape UV tool panel, offset controls and preview window."""
    layout = panel.layout
    obj = getattr(context.scene, "damotified_shape_uv_target", None)

    if obj is None or obj.type != 'MESH':
        return

    mesh = obj.data
    uv = mesh.uv_layers.active
    props = getattr(obj, "uv_translate", None)
    
    if props is None:
        layout.label(text="Properties not registered", icon='ERROR')
        return

    tex = props.texture

    if uv is None:
        layout.label(text="The object has no UV layers", icon='ERROR')
        return
        
    if uv.name == BASE_LAYER:
        layout.label(text=f"'{BASE_LAYER}' is the base layer", icon='ERROR')
        layout.label(text="Select another UV as active")
        return

    addon_name = __package__.rsplit('.', 1)[0]
    prefs = context.preferences.addons.get(addon_name)
    is_debug = prefs.preferences.debug_mode if prefs else False

    # Debug information displays
    # =========================================================
    if is_debug:
        faces_count = len(mesh.polygons)
        
        if faces_count == 1 and tex is not None and tex.size[0] > 0:
            try:
                us = [uv.data[i].uv[0] for i in mesh.polygons[0].loop_indices]
                vs = [uv.data[i].uv[1] for i in mesh.polygons[0].loop_indices]
                
                tw, th = int(tex.size[0]), int(tex.size[1])
                sx = int(round((max(us) - min(us)) * tw))
                sy = int(round((max(vs) - min(vs)) * th))
                
                layout.label(text=f"Mesh Faces: 1   (UV Size: {sx} x {sy} px)")
            except Exception:
                layout.label(text=f"Mesh Faces: 1")
        else:
            layout.label(text=f"Mesh Faces: {faces_count}")

    if tex is not None and tex.size[0] > 0:
        if is_debug:
            layout.label(text=f"Texture: {tex.size[0]} x {tex.size[1]} px")
            layout.label(text=f"1 px in X = {1.0 / tex.size[0]:.5f} UV   1 px in Y = {-1.0 / tex.size[1]:.5f} UV")
    else:
        layout.label(text="No texture: translation disabled", icon='ERROR')

    # Main UI Controls
    # =========================================================
    col = layout.column(align=True)
    col.enabled = tex is not None and tex.size[0] > 0
    
    arm = context.scene.animation_armature
    idx = context.scene.damotified_shape_uv_index
    lst = context.scene.damotified_shape_uv_list
    p_bone = arm.pose.bones.get(lst[idx].name) if arm and 0 <= idx < len(lst) else None
    
    # Custom Step Translation Row X
    # =========================================================
    split_x = col.split(factor=0.66, align=True)
    row_x = split_x.row(align=True)
    
    op_x_minus = row_x.operator(UVTX_OT_translate_step.bl_idname, text="", icon='TRIA_LEFT')
    op_x_minus.axis = 'X'
    op_x_minus.direction = -1
    
    if p_bone and "X shapeUvOffset" in p_bone:
        row_x.prop(p_bone, '["X shapeUvOffset"]', text="X Translation")
    else:
        row_x.prop(props, "px_x")
        
    op_x_plus = row_x.operator(UVTX_OT_translate_step.bl_idname, text="", icon='TRIA_RIGHT')
    op_x_plus.axis = 'X'
    op_x_plus.direction = 1
    
    if p_bone and "X shapeUvOffset" in p_bone:
        row_x.prop_decorator(p_bone, '["X shapeUvOffset"]')
    else:
        row_x.prop_decorator(props, "px_x")
        
    row_step_x = split_x.row(align=True)
    row_step_x.prop(props, "step_x")
    
    if len(mesh.polygons) == 1:
        row_step_x.operator("uvtx.auto_step", text="", icon='CON_SIZELIKE')
    
    # Custom Step Translation Row Y
    # =========================================================
    split_y = col.split(factor=0.66, align=True)
    row_y = split_y.row(align=True)
    
    op_y_minus = row_y.operator(UVTX_OT_translate_step.bl_idname, text="", icon='TRIA_LEFT')
    op_y_minus.axis = 'Y'
    op_y_minus.direction = -1
    
    if p_bone and "Y shapeUvOffset" in p_bone:
        row_y.prop(p_bone, '["Y shapeUvOffset"]', text="Y Translation")
    else:
        row_y.prop(props, "px_y")
        
    op_y_plus = row_y.operator(UVTX_OT_translate_step.bl_idname, text="", icon='TRIA_RIGHT')
    op_y_plus.axis = 'Y'
    op_y_plus.direction = 1
    
    if p_bone and "Y shapeUvOffset" in p_bone:
        row_y.prop_decorator(p_bone, '["Y shapeUvOffset"]')
    else:
        row_y.prop_decorator(props, "px_y")
        
    row_step_y = split_y.row(align=True)
    row_step_y.prop(props, "step_y")
    
    if len(mesh.polygons) == 1:
        row_step_y.operator("uvtx.auto_step", text="", icon='CON_SIZELIKE')

    layout.operator(UVTX_OT_reset.bl_idname, text="↺ Reset Offset", icon='REW')

    # Preview Rendering
    # =========================================================
    if np is None:
        layout.label(text="numpy not available: no preview", icon='ERROR')
        return

    ptr = as_pointer_safe(obj)
    icon = _pv_icon.get(ptr)

    if icon:
        scale = fit_scale(context)
        row_zoom = layout.row(align=True)
        
        op_minus = row_zoom.operator(UVTX_OT_zoom_step.bl_idname, text="", icon='REMOVE')
        op_minus.step = -1
        
        row_zoom.prop(props, "pv_zoom", text="Zoom", slider=True)
        
        op_plus = row_zoom.operator(UVTX_OT_zoom_step.bl_idname, text="", icon='ADD')
        op_plus.step = 1

        row = layout.row()
        row.alignment = 'CENTER'
        row.template_icon(icon, scale=scale)
        
        layout.label(text="Green: Current UV   Magenta: Original UV")
    else:
        layout.label(text="Generating preview...", icon='INFO')
        if not is_preview_throttled():
            _request_preview_throttled(obj)

classes = (
    UVTX_PG_settings,
    UVTX_OT_translate_step,
    UVTX_OT_zoom_step,
    UVTX_OT_reset,
)