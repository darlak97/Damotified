import json
import math
import os
import re
import bpy
import mathutils

def is_mesh_only(node):
    """Checks if a node is a mesh without bone hierarchy."""
    if not isinstance(node, dict):
        return False
        
    node_data = node.get("data", {})
    if isinstance(node_data, dict) and node_data.get("isStaticBox") is True:
        return True
        
    shape = node.get("shape", {})
    settings = shape.get("settings", {})
    if isinstance(settings, dict) and settings.get("isStaticBox") is True:
        return True
        
    return False

def parse_vector(data, default_xy=1.0, default_z=1.0):
    """ Extracts a 3D vector from various formats."""
    if data is None:
        return mathutils.Vector((default_xy, default_xy, default_z))
        
    if isinstance(data, dict):
        return mathutils.Vector((
            data.get("x", default_xy),
            data.get("y", default_xy),
            data.get("z", default_z)
        ))
    elif isinstance(data, (list, tuple)) and len(data) >= 3:
        return mathutils.Vector((float(data[0]), float(data[1]), float(data[2])))
    elif isinstance(data, (list, tuple)) and len(data) == 2:
        return mathutils.Vector((float(data[0]), float(data[1]), default_z))
        
    return mathutils.Vector((default_xy, default_xy, default_z))

def apply_face_uv_transform(face_data, face_name, ox, oy, fw, fh, default_uv_list_func):
    """ Offset, Scaling, Rotation, Mirror for UV vertices."""
    angle = int(face_data.get("angle", 0))
    rot_steps = (angle // 90) % 4
    
    mirror = face_data.get("mirror", {})
    mirror_x = mirror.get("x", False) if isinstance(mirror, dict) else False
    mirror_y = mirror.get("y", False) if isinstance(mirror, dict) else False
    
    shift_table = { #              0                90                180             270
        (False, False): {0: (0.0, 0.0, 0), 1: (-fh, 0.0, 0), 2: (-fw, -fh, 0), 3: (0.0, -fw, 0)},
        (False, True):  {0: (0.0, -fh, 0), 1: (0.0, 0.0, 2), 2: (-fw, 0.0, 0), 3: (-fh, -fw, 0)},
        (True, False):  {0: (-fw, 0.0, 0), 1: (-fh, -fw, 2), 2: (0.0, -fh, 0), 3: (0.0, 0.0, 0)},
        (True, True):   {0: (-fw, -fh, 0), 1: (0.0, -fw, 0), 2: (0.0, 0.0, 0), 3: (-fh, 0.0, 0)},
    }
    
    dx_shift, dy_shift, extra_rot = shift_table[(mirror_x, mirror_y)][rot_steps]
    
    ox += dx_shift
    oy += dy_shift
    
    if rot_steps % 2 == 1:
        box_w, box_h = fh, fw
    else:
        box_w, box_h = fw, fh
    
    xmin, xmax = ox, ox + box_w
    ymin, ymax = oy, oy + box_h
    
    if mirror_x: 
        xmin, xmax = xmax, xmin
    if mirror_y: 
        ymin, ymax = ymax, ymin
    
    base_coords = default_uv_list_func(xmin, xmax, ymin, ymax)
    
    total_rot_steps = (rot_steps + extra_rot) % 4
    is_equal_mirror = (mirror_x == mirror_y)
    
    if face_name == "back":
        if (rot_steps == 1) or (rot_steps == 3 and is_equal_mirror):
            total_rot_steps = (total_rot_steps + 2) % 4
    else:
        if rot_steps == 3 and not is_equal_mirror:
            total_rot_steps = (total_rot_steps + 2) % 4
        
    if total_rot_steps > 0:
        base_coords = base_coords[-total_rot_steps:] + base_coords[:-total_rot_steps]
        
    return base_coords

def get_or_create_cube_shape(context):
    """Creates the custom bone shape collection and cube object."""
    scene_collection = context.scene.collection
    
    shapes_collection = scene_collection.children.get("Object_Shapes")
    if not shapes_collection:
        shapes_collection = bpy.data.collections.new("Object_Shapes")
        scene_collection.children.link(shapes_collection)
        
    shapes_collection.color_tag = 'COLOR_01'
    
    children_list = list(scene_collection.children)
    if children_list and children_list[0] != shapes_collection:
        for col in children_list:
            scene_collection.children.unlink(col)
            
        scene_collection.children.link(shapes_collection)
        for col in children_list:
            if col != shapes_collection:
                scene_collection.children.link(col)
                
    cube_obj = bpy.data.objects.get("Object_Shape_Cube")
    if not cube_obj:
        cube_mesh = bpy.data.meshes.get("Object_Shape_Cube")
        if not cube_mesh:
            cube_mesh = bpy.data.meshes.new("Object_Shape_Cube")
            verts = [(-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
                     (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5)]
            faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
            cube_mesh.from_pydata(verts, [], faces)
            cube_mesh.update()
            
        cube_obj = bpy.data.objects.new("Object_Shape_Cube", cube_mesh)
        shapes_collection.objects.link(cube_obj)
    elif cube_obj.name not in shapes_collection.objects:
        shapes_collection.objects.link(cube_obj)
        
    layer_col = context.view_layer.layer_collection.children.get(shapes_collection.name)
    if layer_col:
        layer_col.exclude = True
        
    return shapes_collection, cube_obj

def create_shape_mesh(context, armature_object, collection, material_name, name, size, stretch, world_matrix, tex_layout, tex_width, tex_height, use_custom_uv_transform, bone_target=None, normal="+Z", apply_copy_scale=True):
    """Creates a mesh object, materials, UVs, and child-of constraints."""
    clean_name = re.sub(r'--C\d+$', '', name)
    get_or_create_cube_shape(context)
    
    # Mesh data initialization
    # =========================================================
    mesh = bpy.data.meshes.new(clean_name + "_Mesh")
    
    verts = [ # (apply stretch values to base vertices)
        (-0.5 * stretch.x, -0.5 * stretch.y, -0.5 * stretch.z),
        ( 0.5 * stretch.x, -0.5 * stretch.y, -0.5 * stretch.z),
        ( 0.5 * stretch.x,  0.5 * stretch.y, -0.5 * stretch.z),
        (-0.5 * stretch.x,  0.5 * stretch.y, -0.5 * stretch.z),
        (-0.5 * stretch.x, -0.5 * stretch.y,  0.5 * stretch.z),
        ( 0.5 * stretch.x, -0.5 * stretch.y,  0.5 * stretch.z),
        ( 0.5 * stretch.x,  0.5 * stretch.y,  0.5 * stretch.z),
        (-0.5 * stretch.x,  0.5 * stretch.y,  0.5 * stretch.z)
    ]
    
    dx, dy, dz = abs(size.x), abs(size.y), abs(size.z)
    tex_w = max(1.0, float(tex_width))
    tex_h = max(1.0, float(tex_height))
    
    def get_uv(px, py):
        return (px / tex_w, 1.0 - (py / tex_h))
        
    # UV mapping and face processing
    # =========================================================
    effective_tex_layout = {}
    
    if normal == "-Z":
        for face_key, face_val in tex_layout.items():
            if face_key == "front":
                effective_tex_layout["back"] = face_val
            elif face_key == "back":
                effective_tex_layout["front"] = face_val
            else:
                effective_tex_layout[face_key] = face_val
    else:
        effective_tex_layout = dict(tex_layout)
        
    all_face_defs = [
        ("back",   (0, 1, 2, 3), dx, dy, lambda x0, x1, y0, y1: [get_uv(x1, y1), get_uv(x0, y1), get_uv(x0, y0), get_uv(x1, y0)]),
        ("front",  (4, 5, 6, 7), dx, dy, lambda x0, x1, y0, y1: [get_uv(x0, y1), get_uv(x1, y1), get_uv(x1, y0), get_uv(x0, y0)]),
        ("bottom", (0, 1, 5, 4), dx, dz, lambda x0, x1, y0, y1: [get_uv(x0, y1), get_uv(x1, y1), get_uv(x1, y0), get_uv(x0, y0)]),
        ("right",  (1, 2, 6, 5), dz, dy, lambda x0, x1, y0, y1: [get_uv(x1, y1), get_uv(x1, y0), get_uv(x0, y0), get_uv(x0, y1)]),
        ("top",    (2, 3, 7, 6), dx, dz, lambda x0, x1, y0, y1: [get_uv(x1, y0), get_uv(x0, y0), get_uv(x0, y1), get_uv(x1, y1)]),
        ("left",   (3, 0, 4, 7), dz, dy, lambda x0, x1, y0, y1: [get_uv(x0, y0), get_uv(x0, y1), get_uv(x1, y1), get_uv(x1, y0)]),
    ]
    
    is_custom = any(k in effective_tex_layout for k in ["front", "back", "top", "bottom", "left", "right"])

    if is_custom:
        active_face_defs = [f for f in all_face_defs if f[0] in effective_tex_layout]
    else:
        active_face_defs = all_face_defs
        
    faces = [f[1] for f in active_face_defs]
    
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    
    uv_layer = mesh.uv_layers.new(name='UVMap')
    
    def process_face_uvs(face_name, fw, fh, default_uv_list_func):
        """Applies individual offset transforms to each face UV."""
        if is_custom:
            face_data = effective_tex_layout[face_name]
            offset = face_data.get("offset", {"x": 0, "y": 0})
            
            if isinstance(offset, dict):
                ox, oy = float(offset.get("x", 0.0)), float(offset.get("y", 0.0))
            else:
                ox = float(offset[0]) if len(offset) > 0 else 0.0
                oy = float(offset[1]) if len(offset) > 1 else 0.0
            
            if use_custom_uv_transform:
                return apply_face_uv_transform(face_data, face_name, ox, oy, fw, fh, default_uv_list_func)
            else:
                xmin, xmax = ox, ox + fw
                ymin, ymax = oy, oy + fh
                return default_uv_list_func(xmin, xmax, ymin, ymax)
        else:
            offset = effective_tex_layout.get("offset", [0.0, 0.0])
            u = offset[0] if isinstance(offset, list) else offset.get("x", 0.0)
            v = offset[1] if isinstance(offset, list) else offset.get("y", 0.0)
            
            if face_name == "back":
                xmin, xmax, ymin, ymax = u + dz + dx + dz, u + dz + dx + dz + dx, v + dz, v + dz + dy
            elif face_name == "front":
                xmin, xmax, ymin, ymax = u + dz, u + dz + dx, v + dz, v + dz + dy
            elif face_name == "bottom":
                xmin, xmax, ymin, ymax = u + dz + dx, u + dz + dx + dx, v, v + dz
            elif face_name == "right":
                xmin, xmax, ymin, ymax = u, u + dz, v + dz, v + dz + dy
            elif face_name == "top":
                xmin, xmax, ymin, ymax = u + dz, u + dz + dx, v, v + dz
            elif face_name == "left":
                xmin, xmax, ymin, ymax = u + dz + dx, u + dz + dx + dz, v + dz, v + dz + dy
                
            return default_uv_list_func(xmin, xmax, ymin, ymax)
            
    uv_coords = []
    
    for face_name, _, fw, fh, default_uv_func in active_face_defs:
        uv_coords.extend(process_face_uvs(face_name, fw, fh, default_uv_func))
        
    for i, loop in enumerate(mesh.loops):
        uv_layer.data[loop.index].uv = uv_coords[i]
        
    # Mesh object creation and scaling
    # =========================================================
    obj = bpy.data.objects.new(clean_name, mesh)
    collection.objects.link(obj)
    
    obj.matrix_world = world_matrix
    
    min_dim = 0.0001
    obj.scale = (
        max(min_dim, abs(size.x)),
        max(min_dim, abs(size.y)),
        max(min_dim, abs(size.z))
    )
    
    # Material assignment
    # =========================================================
    if material_name:
        material = bpy.data.materials.get(material_name)
        if material:
            if obj.data.materials:
                obj.data.materials[0] = material
            else:
                obj.data.materials.append(material)
                
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    
    target_bone = bone_target if bone_target else clean_name
    
    # Rig constraints and drivers
    # =========================================================
    constraint = obj.constraints.new(type='CHILD_OF')
    constraint.target = armature_object
    constraint.subtarget = target_bone
    constraint.use_scale_x = False
    constraint.use_scale_y = False
    constraint.use_scale_z = False
    
    bpy.ops.constraint.childof_set_inverse(constraint=constraint.name, owner='OBJECT')
    
    if apply_copy_scale: # (setup scale and hide drivers for the primary mesh of the bone)
        scale_constraint = obj.constraints.new(type='COPY_SCALE')
        scale_constraint.name = "Copy Scale (Main)"
        scale_constraint.target = armature_object 
        scale_constraint.subtarget = target_bone 
        scale_constraint.use_offset = True
        scale_constraint.target_space = 'LOCAL'
        scale_constraint.owner_space = 'LOCAL'
        
        fcurve_viewport = obj.driver_add("hide_viewport")
        driver_viewport = fcurve_viewport.driver
        driver_viewport.type = 'AVERAGE'
        
        var_viewport = driver_viewport.variables.new()
        var_viewport.name = "hide"
        var_viewport.type = 'SINGLE_PROP'
        
        target_viewport = var_viewport.targets[0]
        target_viewport.id_type = 'OBJECT'
        target_viewport.id = armature_object
        target_viewport.data_path = f'pose.bones["{target_bone}"].hide'
        
    obj.damotified_linked_armature = armature_object
    obj.damotified_linked_bone = target_bone
    obj.damotified_is_main_mesh = apply_copy_scale
    
    return obj

def find_bone_collection_recursive(collection, name):
    """ Search for a bone collection by name."""
    if collection.name == name:
        return collection
        
    if hasattr(collection, "children"):
        for child in collection.children:
            found = find_bone_collection_recursive(child, name)
            if found:
                return found
                
    return None

def get_or_create_child_collection(parent_col, child_name):
    """Create a scene collection under a parent."""
    if child_name in parent_col.children:
        return parent_col.children[child_name]
        
    pattern = re.compile(rf"^{re.escape(child_name)}(\.\d+)?$")
    for child in parent_col.children:
        if pattern.match(child.name):
            return child
            
    new_col = bpy.data.collections.new(child_name)
    parent_col.children.link(new_col)
    
    return new_col

def get_or_create_bone_collection(armature_data, name, parent_col=None):
    """Create a bone collection."""
    if not hasattr(armature_data, "collections"):
        return None
        
    root_collections = [c for c in armature_data.collections if c.parent is None]
    
    for root_col in root_collections:
        found = find_bone_collection_recursive(root_col, name)
        if found:
            return found
            
    new_col = armature_data.collections.new(name)
    if parent_col and hasattr(new_col, "parent"):
        new_col.parent = parent_col
        
    return new_col

def apply_duplicate_constraints(context, armature_object, duplicates_list):
    """Applies Copy Transforms constraints to duplicated bones."""
    if not duplicates_list:
        return
        
    bpy.ops.object.select_all(action='DESELECT')
    armature_object.select_set(True)
    context.view_layer.objects.active = armature_object
    
    bpy.ops.object.posemode_toggle()
    
    for dup_name, princ_name in duplicates_list:
        pose_bone = armature_object.pose.bones.get(dup_name)
        if pose_bone:
            constraint = pose_bone.constraints.new(type='COPY_TRANSFORMS')
            constraint.target = armature_object
            constraint.subtarget = princ_name
            constraint.target_space = 'LOCAL'
            constraint.owner_space = 'LOCAL'
    
    bpy.ops.object.posemode_toggle()

def set_bone_color(rig_object, bone_name, theme_code):
    """Safely applies a theme color to bones."""
    if not rig_object:
        return
        
    pose_bone = rig_object.pose.bones.get(bone_name)
    if pose_bone:
        try:
            pose_bone.color.palette = theme_code
        except Exception:
            pass

def parse_bbmodel_to_blocky(data):
    """Converts BBMODEL structure to Blockymodel format."""
    
    # Map lookups for quick access
    # =========================================================
    groups_map = {g["uuid"]: g for g in data.get("groups", [])}
    elements_map = {e["uuid"]: e for e in data.get("elements", [])}
    
    def euler_to_quat(rot):
        """Converts Euler rotation array to Quaternion dict."""
        import math
        import mathutils
        eu = mathutils.Euler((math.radians(rot[0]), math.radians(rot[1]), math.radians(rot[2])), 'XYZ')
        q = eu.to_quaternion()
        return {"w": q.w, "x": q.x, "y": q.y, "z": q.z}
        
    def build_node(outliner_item, parent_origin, index=1):
        """Recursively builds Blocky nodes from BBModel outliner."""
        
        # Parse mesh elements (strings represent uuids of elements)
        # =========================================================
        if isinstance(outliner_item, str):
            el = elements_map.get(outliner_item)
            
            if not el: 
                return None
            
            # Calculate absolute dimensions
            f = el.get("from", [0, 0, 0])
            t = el.get("to", [0, 0, 0])
            size = [abs(t[0] - f[0]), abs(t[1] - f[1]), abs(t[2] - f[2])]
            
            # Convert global origin to local position relative to parent
            el_origin = el.get("origin", [0, 0, 0])
            local_pos = [el_origin[i] - parent_origin[i] for i in range(3)]
            
            # Calculate shape offset from element origin
            center = [(f[i] + t[i]) / 2.0 for i in range(3)]
            shape_offset = [center[i] - el_origin[i] for i in range(3)]
            
            # Handle stretch and inflation scaling
            # =========================================================
            stretch = [1.0, 1.0, 1.0]
            
            if "stretch" in el:
                raw_stretch = el["stretch"]
                
                if isinstance(raw_stretch, (int, float)):
                    stretch = [float(raw_stretch)] * 3
                elif isinstance(raw_stretch, dict):
                    stretch = [float(raw_stretch.get("x", 1.0)), float(raw_stretch.get("y", 1.0)), float(raw_stretch.get("z", 1.0))]
                elif isinstance(raw_stretch, (list, tuple)) and len(raw_stretch) >= 3:
                    stretch = [float(raw_stretch[0]), float(raw_stretch[1]), float(raw_stretch[2])]
                    
            elif "inflate" in el:
                raw_inflate = el["inflate"]
                
                if isinstance(raw_inflate, (int, float)) and raw_inflate != 0:
                    inf = float(raw_inflate)
                    stretch = [
                        (size[0] + 2 * inf) / size[0] if size[0] > 0 else 1.0,
                        (size[1] + 2 * inf) / size[1] if size[1] > 0 else 1.0,
                        (size[2] + 2 * inf) / size[2] if size[2] > 0 else 1.0
                    ]
                elif isinstance(raw_inflate, (list, tuple)) and len(raw_inflate) >= 3:
                    stretch = [
                        (size[0] + 2 * float(raw_inflate[0])) / size[0] if size[0] > 0 else 1.0,
                        (size[1] + 2 * float(raw_inflate[1])) / size[1] if size[1] > 0 else 1.0,
                        (size[2] + 2 * float(raw_inflate[2])) / size[2] if size[2] > 0 else 1.0
                    ]
                    
            # Parse faces and UV transformations
            # =========================================================
            bb_faces = el.get("faces", {})
            blocky_faces = {}
            
            # Map BBModel face names to Blockymodel standards
            face_map = {
                "north": "back",
                "south": "front",
                "up": "top",
                "down": "bottom",
                "east": "right", 
                "west": "left"   
            }
            
            for f_dir, f_data in bb_faces.items():
                if not f_data:
                    continue
                    
                uv = f_data.get("uv", [0, 0, 0, 0])
                
                # Skip untextured faces
                if f_data.get("texture") is None or (uv[0] == uv[2] and uv[1] == uv[3]):
                    continue
                    
                b_dir = face_map.get(f_dir, f_dir)
                bb_rot = f_data.get("rotation", 0)
                
                base_x = uv[0]
                base_y = uv[1]
                size_x = abs(uv[2] - uv[0])
                size_y = abs(uv[3] - uv[1])
                
                mirror_x = bool(uv[2] < uv[0])
                mirror_y = bool(uv[3] < uv[1])
                
                # Calculate offsets, rotation and mirroring rules
                if bb_rot == 90:
                    offset_x = base_x
                    if mirror_y: 
                        offset_y = base_y - size_y # mirror Y or both
                    else: 
                        offset_y = base_y + size_y # mirror X or no mirror
                        
                elif bb_rot == 180:
                    if mirror_x:
                        offset_x = base_x - size_x
                    else:
                        offset_x = base_x + size_x
                        
                    if mirror_y:
                        offset_y = base_y - size_y
                    else:
                        offset_y = base_y + size_y
                        
                elif bb_rot == 270:
                    offset_y = base_y
                    if mirror_x:
                        offset_x = base_x - size_x
                    else:
                        offset_x = base_x + size_x
                        
                else:
                    offset_x = base_x
                    offset_y = base_y
                    
                # Adjust rotation angle
                if mirror_x == mirror_y:
                    if bb_rot == 270:
                        blocky_rot = 90
                    elif bb_rot == 90:
                        blocky_rot = 270
                    else:
                        blocky_rot = bb_rot
                else:
                    blocky_rot = bb_rot
                
                blocky_faces[b_dir] = {
                    "offset": [offset_x, offset_y],
                    "mirror": {"x": mirror_x, "y": mirror_y},
                    "angle": blocky_rot
                }
                
            # Compile final mesh node
            # =========================================================
            name = el.get('name', 'mesh')
            is_piece_val = el.get("isPiece") or el.get("is_piece") or False
            
            node = {
                "name": name,
                "position": local_pos,
                "isPiece": is_piece_val,
                "data": {
                    "isStaticBox": True
                },
                "shape": {
                    "type": "box",
                    "size": size,
                    "stretch": stretch,
                    "offset": shape_offset,
                    "textureLayout": blocky_faces,
                    "settings": {
                        "isPiece": is_piece_val,
                        "isStaticBox": True
                    }
                },
                "children": []
            }
            
            if "rotation" in el:
                node["orientation"] = euler_to_quat(el["rotation"])
                
            return node
            
        # Parse bone groups (dictionaries)
        # =========================================================
        elif isinstance(outliner_item, dict):
            uuid = outliner_item.get("uuid")
            grp = groups_map.get(uuid)
            
            if not grp: 
                return None
            
            grp_origin = grp.get("origin", [0, 0, 0])
            local_pos = [grp_origin[i] - parent_origin[i] for i in range(3)]
            
            is_piece_val = grp.get("isPiece") or grp.get("is_piece") or False
            
            node = {
                "name": grp.get("name", "Bone"),
                "position": local_pos,
                "isPiece": is_piece_val,
                "shape": {
                    "settings": {"isPiece": is_piece_val}
                },
                "children": []
            }
            
            if "rotation" in grp:
                node["orientation"] = euler_to_quat(grp["rotation"])
                
            for idx, child_item in enumerate(outliner_item.get("children", []), 1):
                child_node = build_node(child_item, grp_origin, idx)
                if child_node:
                    node["children"].append(child_node)
                    
            return node
            
        return None
        
    # Build tree from root outliner items
    # =========================================================
    nodes = []
    
    for idx, item in enumerate(data.get("outliner", []), 1):
        node = build_node(item, [0, 0, 0], idx)
        
        if node:
            nodes.append(node)
            
    data["nodes"] = nodes
    
    return data

def load_blocky_json(filepath, operator_ref=None):
    """Load the file and format to Blockymodel."""
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception as e:
        if operator_ref:
            operator_ref.report({'ERROR'}, f"Could not read the file: {str(e)}")
        return None
        
    data["rig_offsets"] = {}
    
    # BBModel detection
    # =========================================================
    if "outliner" in data and ("elements" in data or "groups" in data):
        if operator_ref:
            operator_ref.report({'INFO'}, "BBMODEL format detected. Structuring unified hierarchy...")
        
        data["format_type"] = "bbmodel"
        
        for grp in data.get("groups", []):
            grp_name = grp.get("name")
            if grp_name and "original_offset" in grp:
                data["rig_offsets"][grp_name] = grp["original_offset"]
                
        data = parse_bbmodel_to_blocky(data)
        
    # Blockymodel detection
    # =========================================================
    else:
        data["format_type"] = "blockymodel"
        
        def extract_blocky_offsets(nodes):
            # shape offsets from Blockymodel nodes
            for node in nodes:
                node_name = node.get("name")
                shape = node.get("shape", {})
                
                if node_name and "offset" in shape:
                    data["rig_offsets"][node_name] = shape["offset"]
                
                children = node.get("children") or node.get("nodes") or []
                extract_blocky_offsets(children)
                
        extract_blocky_offsets(data.get("nodes", []))
        
    if not data.get("nodes"):
        if operator_ref:
            operator_ref.report({'ERROR'}, "The file does not contain a valid 'nodes' list or 'outliner'.")
        return None
        
    return data

def setup_blocky_material(file_name, final_texture_path, default_width=64.0, default_height=64.0, operator_ref=None):
    """Creates a node based material and image texture."""
    mat_name = None
    tex_width = default_width
    tex_height = default_height
    
    if not (final_texture_path and os.path.exists(final_texture_path)):
        return mat_name, tex_width, tex_height
        
    mat_name = f"{file_name}_Texture"
    material = bpy.data.materials.get(mat_name)
    
    if not material:
        material = bpy.data.materials.new(name=mat_name)
        material.use_nodes = True
        material.blend_method = 'CLIP'
        
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    
    if bsdf:
        tex_image = next((n for n in nodes if n.type == 'TEX_IMAGE'), None)
        
        if not tex_image:
            tex_image = nodes.new('ShaderNodeTexImage')
            tex_image.location = (-300, 0)
            
        try:
            norm_target_path = os.path.normpath(os.path.abspath(final_texture_path))
            img = None
            
            for existing_img in bpy.data.images:
                if existing_img.filepath:
                    existing_path = os.path.normpath(os.path.abspath(bpy.path.abspath(existing_img.filepath)))
                    if existing_path == norm_target_path:
                        img = existing_img
                        break
                        
            if not img:
                img = bpy.data.images.load(final_texture_path)
                
            if img:
                tex_width = float(img.size[0])
                tex_height = float(img.size[1])
                
            tex_image.image = img
            tex_image.interpolation = 'Closest'
            tex_image.extension = 'EXTEND'
            
            links.new(tex_image.outputs['Color'], bsdf.inputs['Base Color'])
            links.new(tex_image.outputs['Alpha'], bsdf.inputs['Alpha'])
            
        except Exception as e:
            if operator_ref:
                operator_ref.report({'WARNING'}, f"Could not assign image: {e}")
                
    return mat_name, tex_width, tex_height

def create_config_bone(armature_data, bone, actual_bone_name, config_bones_list):
    """Generates a configuration bone without hierarchy."""
    cfg_bone = armature_data.edit_bones.new(actual_bone_name + "_Config")
    cfg_bone.head = bone.head
    cfg_bone.tail = bone.tail
    cfg_bone.matrix = bone.matrix.copy()
    cfg_bone.length = bone.length
    cfg_bone.parent = None 
    
    config_bones_list.append((cfg_bone.name, actual_bone_name))
    
    return cfg_bone

def apply_config_constraints(rig_object, config_bone_pairs):
    """Adds a 'Child Of' bone constraint to bone."""
    if not rig_object:
        return
        
    for cfg_name, target_bone_name in config_bone_pairs:
        pose_bone = rig_object.pose.bones.get(cfg_name)
        target_bone = rig_object.data.bones.get(target_bone_name)
        
        if pose_bone and target_bone:
            constraint = pose_bone.constraints.new(type='CHILD_OF')
            constraint.name = "Child Of Target"
            constraint.target = rig_object
            constraint.subtarget = target_bone_name
            
            constraint.use_scale_x = False
            constraint.use_scale_y = False
            constraint.use_scale_z = False
            
            constraint.inverse_matrix = target_bone.matrix_local.inverted()

def get_config_parent(armature_data, parent_bone):
    """Returns the config version of a parent bone."""
    if not parent_bone:
        return None
        
    cfg_bone = armature_data.edit_bones.get(parent_bone.name + "_Config")
    
    return cfg_bone if cfg_bone else parent_bone

def apply_custom_shape(armature, bone, bone_name):
    """Assigns custom wireframe visuals."""
    pose_bone = armature.pose.bones.get(bone_name)
    shape_cube = bpy.data.objects.get("Object_Shape_Cube")
    
    if pose_bone and shape_cube:
        pose_bone.custom_shape = shape_cube
        bone.show_wire = True
        pose_bone.custom_shape_wire_width = 2.0

def calculate_and_set_bone_length(bone, child_bones, default_length=3.0, max_limit=None):
    """Calculates dynamic bone length based on minimum child distances."""
    if child_bones:
        min_distance = min((cb.head - bone.head).length for cb in child_bones)
        calculated_length = min_distance * 0.75
        bone.length = max(default_length, calculated_length)
    else:
        bone.length = default_length
        
    if max_limit and bone.length > max_limit:
        bone.length = max_limit

def initialize_blocky_import(filepath, final_texture_path, operator_ref):
    """Parses base data and loads global assets for import."""
    data = load_blocky_json(filepath, operator_ref)
    
    if not data:
        return None
        
    nodes_list = data["nodes"]
    file_name = os.path.splitext(os.path.basename(filepath))[0]
    
    def_w = data.get("resolution", {}).get("width", data.get("textureWidth", 64.0))
    def_h = data.get("resolution", {}).get("height", data.get("textureHeight", 64.0))
    
    mat_name, tex_width, tex_height = setup_blocky_material(
        file_name, final_texture_path, def_w, def_h, operator_ref
    )
    
    return data, nodes_list, file_name, mat_name, tex_width, tex_height

def calculate_node_matrices(node, parent_world_matrix):
    """Calculates final world and local space matrices for nodes."""
    orientation = node.get("orientation", {})
    quaternion = (orientation.get("w", 1.0), orientation.get("x", 0.0), orientation.get("y", 0.0), orientation.get("z", 0.0))
    rot_matrix = mathutils.Quaternion(quaternion).to_matrix().to_4x4()
    
    position = node.get("position") or node.get("translation") or node.get("pivot")
    pos_vec = parse_vector(position, default_xy=0.0, default_z=0.0)
    trans_matrix = mathutils.Matrix.Translation(pos_vec)
    
    local_matrix = trans_matrix @ rot_matrix
    world_matrix = parent_world_matrix @ local_matrix
    
    shape = node.get("shape", {})
    shape_offset_data = shape.get("offset")
    shape_offset = parse_vector(shape_offset_data, default_xy=0.0, default_z=0.0)
    child_base_matrix = world_matrix @ mathutils.Matrix.Translation(shape_offset)
    
    return world_matrix, child_base_matrix, shape

def generate_blocky_meshes(context, target_rig, collection, meshes_to_create, mat_name, tex_width, tex_height):
    """Processes the queued mesh list and generates objects."""
    bones_with_scale = set()
    
    for mesh_data in meshes_to_create:
        obj_name = mesh_data.get("name") or mesh_data.get("obj_name") 
        
        clean_name = re.sub(r'--C\d+$', '', obj_name)
        target_bone = mesh_data.get("bone_target") if mesh_data.get("bone_target") else clean_name
        
        apply_scale = target_bone not in bones_with_scale
        
        if apply_scale:
            bones_with_scale.add(target_bone)
            
        create_shape_mesh(
            context, target_rig, collection, mat_name, obj_name,
            mesh_data["size"], mesh_data["stretch"], mesh_data["matrix"],
            mesh_data["tex_layout"], tex_width, tex_height,
            use_custom_uv_transform=True, 
            bone_target=mesh_data.get("bone_target"),
            normal=mesh_data.get("normal", "+Z"),
            apply_copy_scale=apply_scale # (applies scale to the primary mesh only)
        )

def import_attachment_blockymodel(filepath, final_texture_path, context, target_rig, operator_ref=None):
    """ Import models as attachments linked to armature."""
    scene = context.scene
    initial_mode = context.mode
    initial_active = context.active_object
    current_action = None
    
    # Context preparation and validation
    # =========================================================
    if target_rig and target_rig.animation_data and target_rig.animation_data.action:
        current_action = target_rig.animation_data.action
        target_rig.animation_data.action = None
        
    auto_keying_state = scene.tool_settings.use_keyframe_insert_auto
    
    try:
        scene.tool_settings.use_keyframe_insert_auto = False
        
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
            
        if not target_rig or target_rig.type != 'ARMATURE':
            if operator_ref:
                operator_ref.report({'WARNING'}, "Target Rig not found. Executing normal import.")
            return import_blockymodel(filepath, final_texture_path, context, operator_ref)
            
        # Attachment data initialization
        # =========================================================
        init_data = initialize_blocky_import(filepath, final_texture_path, operator_ref)
        
        if not init_data:
            return {'CANCELLED'}
            
        data, nodes_list, file_name, mat_name, tex_width, tex_height = init_data
        
        def check_is_piece(obj, path="root"):
            """Recursively scans data to ensure valid attachment parts exist."""
            found = False
            
            if isinstance(obj, dict):
                if obj.get('isPiece') is True or obj.get('is_piece') is True:
                    found = True
                    
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        if check_is_piece(v, f"{path}->{k}"):
                            found = True
                            
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    if check_is_piece(item, f"{path}[{idx}]"):
                        found = True
                        
            return found
        
        if not check_is_piece(data):
            if operator_ref:
                operator_ref.report({'WARNING'}, "The imported file does not contain attachment properties")
            return {'CANCELLED'}
        
        armature_data = target_rig.data
        bpy.ops.object.select_all(action='DESELECT')
        target_rig.select_set(True)
        context.view_layer.objects.active = target_rig
        
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='SELECT')
        bpy.ops.pose.transforms_clear()
        bpy.ops.object.mode_set(mode='EDIT')
        
        existing_bone_names = set(armature_data.edit_bones.keys())
        matched_target_bones = set()
        principal_bones_map = {}
        new_bones_created = []
        config_bones_list = []
        duplicates_list = []
        meshes_to_create = []
        
        axis_conversion = mathutils.Matrix.Rotation(math.radians(90), 4, 'X')
        
        # Recursive bone parsing function
        # =========================================================
        def parse_attachment_node(node, parent_bone=None, parent_world_matrix=mathutils.Matrix.Identity(4)):
            """Recursively generates attachment bones and queues meshes."""
            node_name = node.get("name", "Bone")
            is_only_mesh = is_mesh_only(node)
            
            # Matrix calculations
            # =========================================================
            world_matrix, child_base_matrix, shape = calculate_node_matrices(node, parent_world_matrix)
            
            bone_blender_matrix = axis_conversion @ world_matrix
            mesh_blender_matrix = axis_conversion @ child_base_matrix
            
            bone = None
            actual_bone_name = None
            cfg_bone = None
            
            if not is_only_mesh:
                settings = shape.get("settings", {})
                is_piece = (settings.get("isPiece") is True or settings.get("is_piece") is True)
                
                if node_name in existing_bone_names:
                    
                    # Anchor bone handling - target main bone
                    # =========================================================
                    if node_name not in matched_target_bones and is_piece:
                        new_bone_name = f"{file_name}:{node_name}"
                        bone = armature_data.edit_bones.new(new_bone_name)
                        target_main_bone = armature_data.edit_bones.get(node_name)
                        
                        if target_main_bone:
                            bone.parent = get_config_parent(armature_data, target_main_bone)
                            
                            original_offset_vec = mathutils.Vector((0.0, 0.0, 0.0))
                            
                            for obj in bpy.data.objects:
                                if obj.type == 'MESH':
                                    if getattr(obj, "damotified_linked_armature", None) == target_rig and \
                                       getattr(obj, "damotified_linked_bone", "") == node_name and \
                                       getattr(obj, "damotified_is_main_mesh", False):
                                        
                                        local_mat = target_main_bone.matrix.inverted() @ obj.matrix_world
                                        original_offset_vec = local_mat.translation.copy()
                                        break
                                        
                            bone_blender_matrix = target_main_bone.matrix.copy() @ mathutils.Matrix.Translation(original_offset_vec)
                            
                            mesh_blender_matrix = bone_blender_matrix.copy()
                            child_base_matrix = axis_conversion.inverted() @ mesh_blender_matrix
                            
                            if data.get("format_type") == "bbmodel":
                                raw_offset = data.get("rig_offsets", {}).get(node_name, [0.0, 0.0, 0.0])
                                stored_offset = parse_vector(raw_offset, default_xy=0.0, default_z=0.0)
                                child_base_matrix.translation -= stored_offset
                                
                        matched_target_bones.add(node_name)
                        principal_bones_map[node_name] = bone.name
                        
                    else: 
                        bone = armature_data.edit_bones.new(node_name)
                        
                        if parent_bone:
                            bone.parent = get_config_parent(armature_data, parent_bone)
                            
                        if node_name in principal_bones_map:
                            principal_name = principal_bones_map[node_name]
                            duplicates_list.append((bone.name, principal_name))
                else:
                    # General bone creation
                    # =========================================================
                    bone = armature_data.edit_bones.new(node_name)
                    actual_bone_name = bone.name
                    
                    if node_name not in principal_bones_map:
                        principal_bones_map[node_name] = actual_bone_name
                    else:
                        duplicates_list.append((actual_bone_name, principal_bones_map[node_name]))
                        
                    if parent_bone:
                        bone.parent = get_config_parent(armature_data, parent_bone)
                        
                actual_bone_name = bone.name
                new_bones_created.append(actual_bone_name)
                
                bone.head = (0, 0, 0)
                bone.tail = (0, 1, 0)
                bone.matrix = bone_blender_matrix
                
                cfg_bone = create_config_bone(armature_data, bone, actual_bone_name, config_bones_list)
                
            # Mesh queueing
            # =========================================================
            shape_type = shape.get("type", "none")
            
            if shape_type in ["box", "quad"]:
                settings = shape.get("settings", {})
                size_vec = parse_vector(settings.get("size") or shape.get("size"), default_z=0.01)
                stretch_vec = parse_vector(settings.get("stretch") or shape.get("stretch"), default_z=1.0)
                normal_setting = settings.get("normal", "+Z")
                
                target_bone_name = actual_bone_name if not is_only_mesh else (parent_bone.name if parent_bone else None)
                
                meshes_to_create.append({
                    "name": node_name,
                    "bone_target": target_bone_name,
                    "matrix": mesh_blender_matrix,
                    "size": size_vec,
                    "stretch": stretch_vec,
                    "tex_layout": shape.get("textureLayout", {}),
                    "normal": normal_setting
                })
                
            children = node.get("children") or node.get("nodes") or []
            child_bones = []
            
            for child in children:
                next_parent_bone = bone if not is_only_mesh else parent_bone
                
                child_bone = parse_attachment_node(
                    child, 
                    parent_bone=next_parent_bone, 
                    parent_world_matrix=child_base_matrix
                )
                
                if child_bone:
                    child_bones.append(child_bone)
                    
            if not is_only_mesh and bone:
                calculate_and_set_bone_length(bone, child_bones, default_length=2.0, max_limit=20)
                cfg_bone.length = bone.length
                
            return bone if not is_only_mesh else None
            
        for root_node in nodes_list:
            parse_attachment_node(root_node)
            
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Collection management
        # =========================================================
        rig_collection = bpy.data.collections.get(target_rig.name)
        
        if not rig_collection:
            rig_collection = bpy.data.collections.new(target_rig.name)
            if target_rig.users_collection:
                target_rig.users_collection[0].children.link(rig_collection)
            else:
                context.scene.collection.children.link(rig_collection)
                
        attachments_collection = get_or_create_child_collection(rig_collection, "Attachments_Meshes")
        file_attachment_collection = get_or_create_child_collection(attachments_collection, file_name)
        
        actual_file_name = file_attachment_collection.name
        
        col_main = get_or_create_bone_collection(armature_data, "Main_Bones")
        col_main_attach = get_or_create_bone_collection(armature_data, "Attachments", col_main)
        col_file_main = get_or_create_bone_collection(armature_data, actual_file_name, col_main_attach)
        
        col_attach_bones = get_or_create_bone_collection(armature_data, "Additional_Bones")
        col_nubs_global = get_or_create_bone_collection(armature_data, "Bones_Nubs", col_attach_bones)
        col_array_global = get_or_create_bone_collection(armature_data, "Bones_Array", col_attach_bones)
        col_attach_nubs = get_or_create_bone_collection(armature_data, "Attachments_Nubs", col_attach_bones)
        col_file_attach = get_or_create_bone_collection(armature_data, f"{actual_file_name}_Attachments", col_attach_nubs)
        col_config = get_or_create_bone_collection(armature_data, "Bones_Config", col_attach_bones)
        
        if col_attach_bones:
            col_attach_bones.is_visible = False
            
        if col_config:
            col_config.is_visible = False
            
        dup_names_set = {d[0] for d in duplicates_list}
        regex_attachment = re.compile(r'(^|[-_\s])attachment([-_\s]|$)', re.IGNORECASE)
        
        # Bone classification and coloring
        # =========================================================
        for cfg_name, orig_name in config_bones_list:
            cfg_obj = armature_data.bones.get(cfg_name)
            if cfg_obj:
                col_config.assign(cfg_obj)
            set_bone_color(target_rig, cfg_name, 'THEME10')
            
        for bone_name in new_bones_created:
            bone_obj = armature_data.bones.get(bone_name)
            if not bone_obj:
                continue
            
            assigned = False
            
            if ":" in bone_name:
                col_nubs_global.assign(bone_obj)
                col_file_attach.assign(bone_obj)
                assigned = True
                
            if bone_name in dup_names_set:
                col_array_global.assign(bone_obj)
                col_file_attach.assign(bone_obj)
                assigned = True
                set_bone_color(target_rig, bone_name, 'THEME12')
                
            if regex_attachment.search(bone_name):
                col_nubs_global.assign(bone_obj)
                col_file_attach.assign(bone_obj)
                assigned = True
                set_bone_color(target_rig, bone_name, 'THEME15')
                
            if not assigned:
                col_file_main.assign(bone_obj)
                set_bone_color(target_rig, bone_name, 'THEME09')
                apply_custom_shape(target_rig, bone_obj, bone_name)
            else:
                set_bone_color(target_rig, bone_name, 'THEME07')
                
        # Mesh generation and constraints
        # =========================================================
        apply_config_constraints(target_rig, config_bones_list)
        
        generate_blocky_meshes(
            context, target_rig, file_attachment_collection, 
            meshes_to_create, mat_name, tex_width, tex_height
        )
        
        apply_duplicate_constraints(context, target_rig, duplicates_list)
        
        if operator_ref:
            operator_ref.report({'INFO'}, f"Attachment '{actual_file_name}' added successfully.")
            
        return {'FINISHED'}
        
    finally:
        # Absolute cleanup and state restoration
        # =========================================================
        scene.tool_settings.use_keyframe_insert_auto = auto_keying_state
        
        if current_action and target_rig and target_rig.animation_data:
            target_rig.animation_data.action = current_action
            
        if initial_active:
            try:
                if bpy.context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                    
                bpy.ops.object.select_all(action='DESELECT')
                initial_active.select_set(True)
                context.view_layer.objects.active = initial_active
                
                if initial_mode == 'POSE' and initial_active.type == 'ARMATURE':
                    bpy.ops.object.mode_set(mode='POSE')
                elif initial_mode == 'EDIT' and initial_active.type == 'ARMATURE':
                    bpy.ops.object.mode_set(mode='EDIT')
                else:
                    bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

def import_blockymodel(filepath, final_texture_path, context, operator_ref=None, use_custom_uv_transform=True):
    """Importing complete models and building armatures."""
    init_data = initialize_blocky_import(filepath, final_texture_path, operator_ref)
    
    if not init_data:
        return {'CANCELLED'}
        
    data, nodes_list, file_name, mat_name, tex_width, tex_height = init_data
    
    armature_data = bpy.data.armatures.new(file_name)
    armature_object = bpy.data.objects.new(file_name, armature_data)
    armature_object.show_in_front = True
    
    main_collection = bpy.data.collections.new(file_name)
    context.collection.children.link(main_collection)
    
    main_collection.color_tag = 'COLOR_05'
    main_collection.objects.link(armature_object)
    
    model_collection = bpy.data.collections.new("Model_Meshes")
    main_collection.children.link(model_collection)
    
    context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    
    axis_conversion = mathutils.Matrix.Rotation(math.radians(90), 4, 'X')
    
    meshes_to_create = []
    principal_bones_map = {}
    config_bones_list = [] 
    duplicates_list = []
    
    def parse_node(node, parent_bone=None, parent_world_matrix=mathutils.Matrix.Identity(4)):
        # Generates primary bones and queues meshes
        node_name = node.get("name", "Bone")
        
        world_matrix, child_base_matrix, shape = calculate_node_matrices(node, parent_world_matrix)
        is_only_mesh = is_mesh_only(node)
        bone = None
        actual_bone_name = None
        
        if not is_only_mesh:
            bone = armature_data.edit_bones.new(node_name)
            actual_bone_name = bone.name
            
            if node_name not in principal_bones_map:
                principal_bones_map[node_name] = actual_bone_name
            else:
                duplicates_list.append((actual_bone_name, principal_bones_map[node_name]))
                
            bone.head = (0, 0, 0)
            bone.tail = (0, 1, 0) 
            bone.matrix = axis_conversion @ world_matrix
            
            cfg_bone = create_config_bone(armature_data, bone, actual_bone_name, config_bones_list)
            
            if parent_bone:
                bone.parent = get_config_parent(armature_data, parent_bone)
        
        shape_type = shape.get("type", "none")
        
        if shape_type in ["box", "quad"]:
            settings = shape.get("settings", {})
            size_raw = settings.get("size") or shape.get("size")
            stretch_raw = settings.get("stretch") or shape.get("stretch")
            normal_setting = settings.get("normal", "+Z")
            
            size_vec = parse_vector(size_raw, default_z=0.01)
            stretch_vec = parse_vector(stretch_raw, default_z=1.0)
            mesh_world_matrix = axis_conversion @ child_base_matrix
            
            target_bone_name = actual_bone_name if not is_only_mesh else (parent_bone.name if parent_bone else None)
            
            meshes_to_create.append({
                "obj_name": node_name,
                "bone_target": target_bone_name,
                "matrix": mesh_world_matrix,
                "size": size_vec,
                "stretch": stretch_vec,
                "tex_layout": shape.get("textureLayout", {}),
                "normal": normal_setting
            })
            
        children = node.get("children") or node.get("nodes") or []
        child_bones = []
        
        for child in children:
            next_parent_bone = bone if not is_only_mesh else parent_bone
            
            child_bone = parse_node(
                child,
                parent_bone=next_parent_bone,
                parent_world_matrix=child_base_matrix,
            )
            
            if child_bone:
                child_bones.append(child_bone)
                
        if not is_only_mesh and bone:
            max_len = 20.0 if node_name == "Origin" else None
            calculate_and_set_bone_length(bone, child_bones, default_length=3.0, max_limit=max_len)
            cfg_bone.length = bone.length
            
        return bone if not is_only_mesh else None
        
    for root_node in nodes_list:
        parse_node(root_node)
        
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Base rig collection management
    # =========================================================
    if hasattr(armature_data, "collections"):
        col_main = get_or_create_bone_collection(armature_data, "Main_Bones")
        col_model = get_or_create_bone_collection(armature_data, "Model_Bones", col_main)
        col_items = get_or_create_bone_collection(armature_data, "Items_Attachments", col_main)
        col_origin = get_or_create_bone_collection(armature_data, "Origin", col_main)
        
        col_attach = get_or_create_bone_collection(armature_data, "Additional_Bones")
        col_nubs = get_or_create_bone_collection(armature_data, "Bones_Nubs", col_attach)
        col_array = get_or_create_bone_collection(armature_data, "Bones_Array", col_attach)
        col_config = get_or_create_bone_collection(armature_data, "Bones_Config", col_attach)
        
        col_attach.is_visible = False
        col_config.is_visible = False
        
        regex_origin = re.compile(r'(^|[-_\s])origin([-_\s]|$)', re.IGNORECASE)
        regex_attachment = re.compile(r'(^|[-_\s])attachment([-_\s]|$)', re.IGNORECASE)
        
        dup_names_set = {d[0] for d in duplicates_list} 
        config_names_set = {item[0] for item in config_bones_list}
        
        get_or_create_cube_shape(context)
        
        for bone in armature_data.bones:
            bone_name = bone.name
            
            if bone_name in config_names_set:
                col_config.assign(bone)
                set_bone_color(armature_object, bone_name, 'THEME10')
                continue
                
            assigned = False
            
            if bone_name in dup_names_set:
                col_array.assign(bone)
                assigned = True
                set_bone_color(armature_object, bone_name, 'THEME12')
            
            if regex_origin.search(bone_name):
                col_origin.assign(bone)
                assigned = True
                set_bone_color(armature_object, bone_name, 'THEME08')
                apply_custom_shape(armature_object, bone, bone_name)
                
            if bone_name in ["R-Attachment", "L-Attachment"]:
                col_items.assign(bone)
                assigned = True
                set_bone_color(armature_object, bone_name, 'THEME13')
                apply_custom_shape(armature_object, bone, bone_name)
                
            if regex_attachment.search(bone_name):
                col_nubs.assign(bone)
                assigned = True
                set_bone_color(armature_object, bone_name, 'THEME09')
                
            if not assigned:
                col_model.assign(bone)
                apply_custom_shape(armature_object, bone, bone_name)
                
        apply_config_constraints(armature_object, config_bones_list)
        
    generate_blocky_meshes(
        context, armature_object, model_collection, 
        meshes_to_create, mat_name, tex_width, tex_height
    )
    
    apply_duplicate_constraints(context, armature_object, duplicates_list)
    
    bpy.ops.object.select_all(action='DESELECT')
    armature_object.select_set(True)
    context.view_layer.objects.active = armature_object
    
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'
                    
    tex_info = f"Texture loaded: '{os.path.basename(final_texture_path)}'" if mat_name else "No material or texture assigned"
    
    if operator_ref:
        operator_ref.report(
            {'INFO'},
            f"Rig imported ({len(armature_data.bones)} bones, {len(meshes_to_create)} meshes). {tex_info}.",
        )
        
    return {'FINISHED'}