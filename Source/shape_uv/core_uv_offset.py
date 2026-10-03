import os
import bpy
import bmesh

try:
    import numpy as np
except ImportError:
    np = None

BASE_LAYER = "UVTX_BASE"
TARGET_KEY = "_uvtx_target_uv"
PREVIEW_MAX = 256
OUT_DARK = 0.11
MAX_PREVIEW_POLYS = 10000

# Global cache
_BUSY = False    
_pcoll = None    
_pv_icon = {}    
_pv_state = {}   
_pv_rev = {}     
_last_px = {}    
_pv_file_rev = {}
_pv_keys = {}    
_pv_file = {}    
_tile_cache = {} 

def init_globals():
    """Preview collection and clears variable cache."""
    global _pcoll
    import bpy.utils.previews
    _pcoll = bpy.utils.previews.new()
    
    _pv_icon.clear()
    _pv_state.clear()
    _pv_rev.clear()
    _last_px.clear()
    _pv_file_rev.clear()
    _pv_keys.clear()
    _pv_file.clear()
    _tile_cache.clear()

def clear_globals():
    """Clears icons, memory, and temporary files upon add-on shutdown."""
    global _pcoll
    
    for path in list(_pv_file.values()):
        try:
            os.remove(path)
        except Exception:
            pass

    if _pcoll is not None:
        try:
            bpy.utils.previews.remove(_pcoll)
        except Exception:
            pass
        _pcoll = None
        
    _pv_icon.clear()
    _pv_state.clear()
    _pv_rev.clear()
    _last_px.clear()
    _pv_file_rev.clear()
    _pv_keys.clear()
    _pv_file.clear()
    _tile_cache.clear()

# General Utilities
# =========================================================

def find_object_image(obj):
    """ Extract the active texture image from the objects material."""
    try:
        for slot in obj.material_slots:
            mat = slot.material
            
            if mat is None or not mat.use_nodes or mat.node_tree is None:
                continue
                
            nodes = mat.node_tree.nodes
            
            for node in nodes:
                if getattr(node, "type", "") == 'TEX_IMAGE' and node.image:
                    return node.image
                    
            for node in nodes:
                img = getattr(node, "image", None)
                if img is not None:
                    return img
    except Exception:
        pass

    for img in bpy.data.images:
        if img.name.startswith(("Render Result", "Viewer Node", "UVTX_Preview_")):
            continue
            
        if img.source in {'FILE', 'GENERATED', 'TILED', 'SEQUENCE', 'MOVIE'}:
            try:
                if img.size[0] > 0 and img.size[1] > 0:
                    return img
            except Exception:
                continue
                
    return None

def _redraw(context=None):
    """ Redraw of all active windows."""
    try:
        ctx = context if context is not None else bpy.context
        wm = ctx.window_manager
        if wm is None:
            return
            
        for window in wm.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass

def _get_bm(mesh):
    """ Extracts bmesh from edit mode."""
    try:
        return bmesh.from_edit_mesh(mesh)
    except Exception:
        return None

def _read_uv(layer, n):
    """ Read flat UV arrays."""
    size = n * 2
    buf = [0.0] * size
    
    try:
        layer.uv.foreach_get("vector", buf)
        return buf
    except Exception:
        pass
        
    try:
        buf = [0.0] * size
        layer.data.foreach_get("uv", buf)
        return buf
    except Exception:
        pass
        
    buf = [0.0] * size
    
    try:
        coll = layer.uv
    except Exception:
        coll = layer.data
        
    for i, item in enumerate(coll):
        try:
            v = item.vector
        except Exception:
            v = item.uv
            
        buf[i * 2] = v[0]
        buf[i * 2 + 1] = v[1]
        
    return buf

def _write_uv(layer, buf):
    """ Write flat UV arrays."""
    try:
        layer.uv.foreach_set("vector", buf)
        return True
    except Exception:
        pass
        
    try:
        layer.data.foreach_set("uv", buf)
        return True
    except Exception:
        pass
        
    try:
        coll = layer.uv
    except Exception:
        coll = layer.data
        
    for i, item in enumerate(coll):
        val = (buf[i * 2], buf[i * 2 + 1])
        try:
            item.vector = val
        except Exception:
            item.uv = val
            
    return True

def _uv_offset(props):
    """Calculates internal 0-1 float offset based on UI pixel values."""
    px = int(props.px_x)
    py = int(props.px_y)
    
    if px == 0 and py == 0:
        return 0.0, 0.0 
        
    img = props.texture
    if img is None:
        return None
        
    w, h = img.size
    
    if w <= 0 or h <= 0:
        return None
        
    return px / float(w), -py / float(h)

def setup_geonodes_drivers(obj, armature, bone_name):
    """Generates a unique Geometry Nodes modifier to translate UVs."""
    if not obj or not armature or getattr(obj, 'type', '') != 'MESH': 
        return
    
    # Remove Mapping and TexCoord nodes
    # =========================================================
    if obj.active_material and obj.active_material.use_nodes:
        nodes = obj.active_material.node_tree.nodes
        mapping = next((n for n in nodes if n.type == 'MAPPING'), None)
        tex_coord = next((n for n in nodes if n.type == 'TEX_COORD'), None)
        
        if mapping and tex_coord:
            nodes.remove(mapping)
            nodes.remove(tex_coord)

    # Geometry Nodes modifier generation
    # =========================================================
    mod_name = "ShapeUV_Transform"
    mod = obj.modifiers.get(mod_name)
    
    if not mod:
        mod = obj.modifiers.new(name=mod_name, type='NODES')
        mod.show_expanded = False
        
    # Unique node group creation
    # =========================================================
    ng_name = f"ShapeUV_{obj.name}"
    ng = bpy.data.node_groups.get(ng_name)
    
    if not ng:
        ng = bpy.data.node_groups.new(ng_name, 'GeometryNodeTree')
        mod.node_group = ng
        
        if hasattr(ng, "interface"): # (blender 4.0 / 5.0 compatibility)
            ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
            ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
        else:
            ng.inputs.new('NodeSocketGeometry', "Geometry")
            ng.outputs.new('NodeSocketGeometry', "Geometry")
            
        node_in = ng.nodes.new('NodeGroupInput')
        node_in.location = (-400, 0)
        
        node_out = ng.nodes.new('NodeGroupOutput')
        node_out.location = (400, 0)
        
        node_attr = ng.nodes.new('GeometryNodeInputNamedAttribute')
        node_attr.data_type = 'FLOAT_VECTOR'
        node_attr.location = (-200, -100)
        node_attr.name = "UV_Read"
        
        node_add = ng.nodes.new('ShaderNodeVectorMath')
        node_add.operation = 'ADD'
        node_add.location = (0, -100)
        node_add.name = "UV_Add"
        
        node_store = ng.nodes.new('GeometryNodeStoreNamedAttribute')
        node_store.data_type = 'FLOAT2'  
        node_store.domain = 'CORNER'     
        node_store.location = (200, 0)
        node_store.name = "UV_Write"
        
        ng.links.new(node_in.outputs[0], node_store.inputs["Geometry"])
        ng.links.new(node_attr.outputs["Attribute"], node_add.inputs[0])
        ng.links.new(node_add.outputs["Vector"], node_store.inputs["Value"])
        ng.links.new(node_store.outputs["Geometry"], node_out.inputs[0])
    else:
        node_attr = ng.nodes.get("UV_Read")
        node_add = ng.nodes.get("UV_Add")
        node_store = ng.nodes.get("UV_Write")

    # UV Map targeting
    # =========================================================
    uv_name = obj.data.uv_layers.active.name if obj.data.uv_layers.active else "UVMap"
    if node_attr: 
        node_attr.inputs["Name"].default_value = uv_name
    if node_store: 
        node_store.inputs["Name"].default_value = uv_name
    
    # Bone driver setup
    # =========================================================
    if node_add:
        tex_w, tex_h = 1024.0, 1024.0
        props = getattr(obj, "uv_translate", None)
        
        if props and props.texture:
            tex_w = float(props.texture.size[0])
            tex_h = float(props.texture.size[1])
        
        node_add.inputs[1].driver_remove('default_value')
        
        for i, axis, dim in ((0, 'X', tex_w), (1, 'Y', tex_h)):
            d = node_add.inputs[1].driver_add('default_value', i).driver
            d.type = 'SCRIPTED'
            
            for v in d.variables:
                d.variables.remove(v)
                
            var = d.variables.new()
            var.name = "val"
            var.type = 'SINGLE_PROP'
            var.targets[0].id_type = 'OBJECT'
            var.targets[0].id = armature
            var.targets[0].data_path = f'pose.bones["{bone_name}"]["{axis} shapeUvOffset"]'

            if i == 0:
                d.expression = f"val / {dim}"
            else:
                d.expression = f"-val / {dim}" # invert Y-axis for Geometry Nodes
            
    # Force Depsgraph update
    # =========================================================
    ng.update_tag()
    obj.update_tag()
    armature.update_tag()

def as_pointer_safe(id_block):
    """ Extract memory pointer from Blender data."""
    try:
        return id_block.as_pointer()
    except Exception:
        return 0

# =========================================================
# Preview logic
# =========================================================

def _sampled_tile(src, iw, ih, region=None):
    """Extracts and scales a subsection of an image using numpy for the preview window."""
    w, h = int(src.size[0]), int(src.size[1])
    
    if region is None:
        rx, ry, rw, rh = 0.0, 0.0, float(w), float(h)
    else:
        rx, ry, rw, rh = (float(v) for v in region)
        if rw <= 0 or rh <= 0:
            rx, ry, rw, rh = 0.0, 0.0, float(w), float(h)
            
    key = (src.as_pointer(), w, h, iw, ih,
           round(rx, 3), round(ry, 3), round(rw, 3), round(rh, 3))
           
    cached = _tile_cache.get(src.as_pointer())
    
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]

    arr = np.empty(w * h * 4, np.float32)
    src.pixels.foreach_get(arr)
    arr = arr.reshape(h, w, 4)
    
    cols_f = rx + (np.arange(iw, dtype=np.float64) + 0.5) * rw / iw
    rows_f = ry + (np.arange(ih, dtype=np.float64) + 0.5) * rh / ih
    ci = np.floor(cols_f).astype(np.int32)
    ri = np.floor(rows_f).astype(np.int32)
    
    ok_c = (ci >= 0) & (ci < w)
    ok_r = (ri >= 0) & (ri < h)
    inside = ok_r[:, None] & ok_c[None, :]
    
    tile = np.ascontiguousarray(
        arr[np.ix_(np.clip(ri, 0, h - 1), np.clip(ci, 0, w - 1))])
    tile *= inside[..., None]
    
    _tile_cache[src.as_pointer()] = (key, tile, inside)
    
    return tile, inside

def _checker(h, w, cell=8):
    """Checkerboard background."""
    yy = np.arange(h)[:, None] // cell
    xx = np.arange(w)[None, :] // cell
    return ((yy + xx) % 2 * 0.22 + 0.42).astype(np.float32)

def _draw_segments(buf, width, height, segs, color):
    """Rasterizes numpy segment vectors directly into the image pixel buffer."""
    if not segs:
        return
        
    a = np.asarray(segs, np.float64)
    
    mask = np.isfinite(a).all(axis=1) # Remove NaN/Infinity coordinate
    a = a[mask]
    
    if len(a) == 0:
        return
        
    x0, y0, x1, y1 = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    
    # Clipping to prevent RAM over
    # =========================================================
    margin = 100
    x0 = np.clip(x0, -margin, width + margin)
    x1 = np.clip(x1, -margin, width + margin)
    y0 = np.clip(y0, -margin, height + margin)
    y1 = np.clip(y1, -margin, height + margin)
    
    steps = np.ceil(np.maximum(np.abs(x1 - x0), np.abs(y1 - y0))).astype(np.int64)
    steps = np.maximum(steps, 1)
    e = len(a)
    
    idx = np.repeat(np.arange(e), steps)
    cum = np.zeros(e + 1, np.int64)
    np.cumsum(steps, out=cum[1:])
    
    local = np.arange(cum[-1], dtype=np.float64) - cum[idx]
    t = local / steps[idx]
    
    xs = x0[idx] + (x1 - x0)[idx] * t
    ys = y0[idx] + (y1 - y0)[idx] * t
    
    xs = np.nan_to_num(xs, nan=-1.0, posinf=-1.0, neginf=-1.0)
    ys = np.nan_to_num(ys, nan=-1.0, posinf=-1.0, neginf=-1.0)
    
    xi = np.rint(xs).astype(np.int32)
    yi = np.rint(ys).astype(np.int32)
    m = (xi >= 0) & (xi < width) & (yi >= 0) & (yi < height)
    
    # Safe drawing
    buf[yi[m], xi[m], 0] = color[0]
    buf[yi[m], xi[m], 1] = color[1]
    buf[yi[m], xi[m], 2] = color[2]
    buf[yi[m], xi[m], 3] = 1.0

def _uv_segments(mesh, uvs, region, tw, th, iw, ih):
    """Converts continuous UV polygon data."""
    segs = []
    rx, ry, rw, rh = region
    
    sx = iw / float(rw) if rw else 1.0
    sy = ih / float(rh) if rh else 1.0
    npoly = len(mesh.polygons)
    
    if npoly == 0 or len(uvs) == 0:
        return segs
        
    pstep = max(1, npoly // MAX_PREVIEW_POLYS)
    
    for pi in range(0, npoly, pstep):
        li = mesh.polygons[pi].loop_indices
        k = len(li)
        if k < 2:
            continue
            
        pts = uvs[list(li)]
        cx = (pts[:, 0] * tw - rx) * sx
        cy = (pts[:, 1] * th - ry) * sy
        
        for e in range(k):
            n = (e + 1) % k
            segs.append((cx[e], cy[e], cx[n], cy[n]))
            
    return segs

def compose_preview(obj):
    """Generate the transparent image and offset UV lines."""
    if np is None:
        return False
        
    props = obj.uv_translate
    mesh = obj.data
    uv = mesh.uv_layers.active
    
    if uv is None:
        return False

    if obj.mode == 'EDIT':
        try: 
            obj.update_from_editmode()
        except Exception: 
            pass

    src = props.texture
    has_tex = (src is not None and src.size[0] > 0 and src.size[1] > 0)
    zoom = max(1, int(getattr(props, "pv_zoom", 1) or 1))

    n = len(mesh.loops)
    uvs = (np.asarray(_read_uv(uv, n), np.float32).reshape(-1, 2)
           if n else np.zeros((0, 2), np.float32))
           
    base_uvs = uvs.copy()

    if has_tex:
        tw, th = int(src.size[0]), int(src.size[1])
    else:
        tw = th = PREVIEW_MAX
        
    # Mathematical offset simulation for the preview UI wireframe
    # =========================================================
    px, py = int(props.px_x), int(props.px_y)
    
    if has_tex and (px != 0 or py != 0) and n:
        ox = px / float(tw)
        oy = -py / float(th) # invert Y to match visual direction
        
        shifted_uvs = uvs.copy()
        shifted_uvs[:, 0] += ox
        shifted_uvs[:, 1] += oy
    else:
        shifted_uvs = uvs

    # Viewport scaling and zoom handling
    # =========================================================
    if has_tex and zoom == 1:
        rx, ry, rw, rh = 0.0, 0.0, float(tw), float(th)
        s = PREVIEW_MAX / float(max(tw, th))
        iw = max(1, int(round(tw * s)))
        ih = max(1, int(round(th * s)))
    else:
        if len(shifted_uvs):
            cx = (float(shifted_uvs[:, 0].min()) + float(shifted_uvs[:, 0].max())) * 0.5
            cy = (float(shifted_uvs[:, 1].min()) + float(shifted_uvs[:, 1].max())) * 0.5
        else:
            cx = cy = 0.5
            
        zoom_factor = 1.0 + (zoom - 1) * 0.05 + ((zoom - 1) ** 2) * 0.08
        side = max(tw, th) / zoom_factor
        
        rx = cx * tw - side * 0.5
        ry = cy * th - side * 0.5
        rw = rh = side
        iw = ih = PREVIEW_MAX
        
    win = (rx, ry, rw, rh)

    prev = props.preview_image
    
    try:
        if prev is not None and (prev.size[0] != iw or prev.size[1] != ih):
            bpy.data.images.remove(prev)
            prev = None
            
        if prev is None:
            prev = bpy.data.images.new(
                name="UVTX_Preview_%s" % obj.name,
                width=iw, height=ih, alpha=True)
            props.preview_image = prev
    except Exception:
        return False

    # Transparency composition
    # =========================================================
    buf = np.zeros((ih, iw, 4), np.float32) # start buffer transparent alpha=0
    
    if has_tex:
        try: 
            tile, inside = _sampled_tile(src, iw, ih, win)
        except Exception: 
            tile, inside = None, None
        
        if tile is not None:
            mask = inside[..., None]
            out_bounds = np.array([0.11, 0.11, 0.11, 0.4], dtype=np.float32) # darken area out of texture limits
            buf = np.where(mask, tile, out_bounds) # paste texture respecting

    _draw_segments(buf, iw, ih, _uv_segments(mesh, base_uvs, win, tw, th, iw, ih), (1.0, 0.15, 0.9)) # magenta baseline
    _draw_segments(buf, iw, ih, _uv_segments(mesh, shifted_uvs, win, tw, th, iw, ih), (0.1, 1.0, 0.3)) # green offset

    try:
        prev.pixels.foreach_set(np.ascontiguousarray(buf).reshape(-1))
        prev.update()
    except Exception:
        return False
        
    return True

def fit_scale(context):
    """Calculates responsive UI scaling for preview."""
    region = getattr(context, "region", None)
    width = float(getattr(region, "width", 0) or 0)
    
    if width <= 0:
        width = 280.0
        
    ui = 1.0
    
    try:
        ui = float(bpy.app.preferences.system.ui_scale) or 1.0
    except Exception:
        pass
        
    unit = 23.0 * ui             
    avail = max(width - 28.0, 60.0)
    
    return max(5.0, min(avail / unit, 25.0))

def _preview_state(obj, props, uv):
    """Generates a state hash string to verify UI."""
    ptr = as_pointer_safe(obj)
    tex_ptr = as_pointer_safe(props.texture) if props.texture else 0
    
    if props.texture:
        tw, th = int(props.texture.size[0]), int(props.texture.size[1])
    else:
        tw = th = 0
        
    return "%d|%d|%d|%d|%d|%d|%s|%d|%d" % (
        int(props.px_x), int(props.px_y), int(getattr(props, "pv_zoom", 1)),
        tex_ptr, tw, th, uv.name if uv else "", len(obj.data.loops),
        _pv_rev.get(ptr, 0))

def refresh_preview(obj, force=False):
    """Main method for updating and saving the preview temp image."""
    global _pcoll
    props = obj.uv_translate
    uv = obj.data.uv_layers.active
    
    if uv is None or _pcoll is None:
        return None

    ptr = as_pointer_safe(obj)
    state = _preview_state(obj, props, uv)
    old_icon = _pv_icon.get(ptr)
    
    if not force and _pv_state.get(ptr) == state and old_icon is not None:
        return old_icon

    try:
        ok = compose_preview(obj)
    except Exception:
        ok = False
        
    if not ok:
        _pv_state[ptr] = state  
        return old_icon
        
    prev = props.preview_image
    
    if prev is None:
        _pv_state[ptr] = state
        return old_icon

    frev = _pv_file_rev.get(ptr, 0) + 1
    
    try:
        import tempfile
        tmp = bpy.app.tempdir or tempfile.gettempdir()
        path = os.path.join(tmp, "uvtx_preview_%d_%d.png" % (ptr, frev))
        
        prev.filepath_raw = path
        prev.file_format = 'PNG'
        prev.save()
    except Exception:
        _pv_state[ptr] = state
        return old_icon

    new_key = "uvtx_pv_%d_%d" % (ptr, frev)
    
    try:
        _pcoll.load(new_key, path, 'IMAGE', force_reload=True)
        icon = _pcoll[new_key].icon_id
    except Exception:
        _pv_state[ptr] = state
        
        try:
            os.remove(path)
        except Exception:
            pass
            
        return old_icon

    old_key = _pv_keys.get(ptr)
    old_file = _pv_file.get(ptr)
    
    if old_key and old_key in _pcoll:
        try:
            del _pcoll[old_key]
        except Exception:
            pass
            
    if old_file and old_file != path:
        try:
            os.remove(old_file)
        except Exception:
            pass

    _pv_keys[ptr] = new_key
    _pv_file[ptr] = path
    _pv_file_rev[ptr] = frev
    _pv_icon[ptr] = icon
    _pv_state[ptr] = state
    
    return icon

def _release_preview(obj):
    """Frees preview memory keys and removes temporary images."""
    global _pcoll
    ptr = as_pointer_safe(obj)
    _pv_icon.pop(ptr, None)
    _pv_state.pop(ptr, None)
    _pv_file_rev.pop(ptr, None)
    key = _pv_keys.pop(ptr, None)
    path = _pv_file.pop(ptr, None)
    
    if _pcoll is not None and key and key in _pcoll:
        try:
            del _pcoll[key]
        except Exception:
            pass
            
    if path:
        try:
            os.remove(path)
        except Exception:
            pass

def refresh_preview_if_editing(obj):
    try:
        refresh_preview(obj, force=True)
    except Exception:
        pass

# Property callbacks and throttling
# =========================================================
_throttle_preview_active = False
_throttle_preview_obj = None

def is_preview_throttled():
    """Returns True if a preview update if is waiting in queue."""
    global _throttle_preview_active
    return _throttle_preview_active

def _execute_throttled_preview():
    """Generates the preview safely in the background thread."""
    global _throttle_preview_active, _throttle_preview_obj
    _throttle_preview_active = False
    obj = _throttle_preview_obj
    
    if obj:
        try:
            _ = obj.name # validate object still exists in Blender
            refresh_preview(obj, force=True)
            _redraw()
        except ReferenceError:
            pass # user deleted object before timer ended
        except Exception as e:
            print(f"[Damotified] Preview Update Error: {e}")
            
    return None

def _request_preview_throttled(obj):
    """Requests a preview update but waits to prevent UI freezing."""
    global _throttle_preview_active, _throttle_preview_obj
    _throttle_preview_obj = obj
    
    if not _throttle_preview_active:
        _throttle_preview_active = True
        bpy.app.timers.register(_execute_throttled_preview, first_interval=0.15)

def _resolve_steps_and_limits(props):
    """Clamps requested UV offset against the texture resolution limits."""
    obj = props.id_data
    ptr = as_pointer_safe(obj)
    px, py = int(props.px_x), int(props.px_y)
    
    img = props.texture
    if img is not None and img.size[0] > 0 and img.size[1] > 0:
        lim_x = int(img.size[0]) + 100
        lim_y = int(img.size[1]) + 100
        px = max(-lim_x, min(lim_x, px))
        py = max(-lim_y, min(lim_y, py))
        
    if px != int(props.px_x):
        props.px_x = px      
    if py != int(props.px_y):
        props.px_y = py
        
    _last_px[ptr] = (int(props.px_x), int(props.px_y))

def _on_uv_offset_update(self, context):
    """Callback when the user modifies X or Y pixel offsets."""
    obj = self.id_data  
    if getattr(obj, "type", None) != 'MESH':
        return
        
    try:
        _resolve_steps_and_limits(self)   
    except Exception:
        pass
        
    # Synchronize UI proxy values to bone properties in real time
    # =========================================================
    try:
        arm = context.scene.animation_armature
        idx = context.scene.damotified_shape_uv_index
        lst = context.scene.damotified_shape_uv_list
        
        if arm and 0 <= idx < len(lst):
            p_bone = arm.pose.bones.get(lst[idx].name)
            
            if p_bone:
                if p_bone.get("X shapeUvOffset") != self.px_x:
                    p_bone["X shapeUvOffset"] = self.px_x
                if p_bone.get("Y shapeUvOffset") != self.px_y:
                    p_bone["Y shapeUvOffset"] = self.px_y
    except Exception:
        pass
        
    _request_preview_throttled(obj)
    _redraw(context)

def _auto_steps(obj):
    """Calculates the exact UV size in pixels and applies it to the steps."""
    props = obj.uv_translate
    mesh = obj.data
    
    if len(mesh.polygons) != 1: # Only for 1 face meshes
        return                      
        
    uv = mesh.uv_layers.active
    if uv is None:
        return
        
    img = props.texture
    if img is None or img.size[0] <= 0 or img.size[1] <= 0:
        return
        
    n = len(mesh.loops)
    flat = _read_uv(uv, n)
    li = mesh.polygons[0].loop_indices
    us = [flat[2 * i] for i in li if 2 * i + 1 < len(flat)]
    vs = [flat[2 * i + 1] for i in li if 2 * i + 1 < len(flat)]
    
    if not us:
        return
        
    tw, th = int(img.size[0]), int(img.size[1])
    sx = int(round((max(us) - min(us)) * tw))
    sy = int(round((max(vs) - min(vs)) * th))
    
    if sx > 0:
        props.step_x = sx
    if sy > 0:
        props.step_y = sy

def _on_pv_zoom_update(self, context):
    """Callback fired when preview zoom slider changes."""
    obj = self.id_data  
    if getattr(obj, "type", None) != 'MESH':
        return
        
    _request_preview_throttled(obj)
    _redraw(context)