import bpy
import json
import re
import logging
from mathutils import Vector

def clean_delta_decimals(delta, is_orientation=False):
    """Recursively cleans floats to target precision."""
    precision = 4 if is_orientation else 2
    
    if isinstance(delta, dict):
        return {k: clean_delta_decimals(v, is_orientation) for k, v in delta.items()}
    elif isinstance(delta, list):
        return [clean_delta_decimals(v, is_orientation) for v in delta]
        
    elif isinstance(delta, (int, float)) and not isinstance(delta, bool): # Ignore booleans
        val = round(delta, precision)
        return int(val) if val == int(val) else val # Strip decimal
        
    return delta

def get_bone_uv_keyframes(action, bone_name, fps_factor):
    """Extracts X and Y shapeUvOffset curves from the action and formats."""
    if not action:
        return []
        
    uv_data = {}
    path_x = f'pose.bones["{bone_name}"]["X shapeUvOffset"]'
    path_y = f'pose.bones["{bone_name}"]["Y shapeUvOffset"]'
    
    fcurves = []
    
    if hasattr(action, 'layers'):
        for layer in action.layers:
            if hasattr(layer, 'strips'):
                for strip in layer.strips:
                    if hasattr(strip, 'channelbag') and strip.channelbag:
                        if hasattr(strip.channelbag, 'fcurves'):
                            fcurves.extend(list(strip.channelbag.fcurves))
                    if hasattr(strip, 'channelbags'):
                        for cb in strip.channelbags:
                            if hasattr(cb, 'fcurves'):
                                fcurves.extend(list(cb.fcurves))
                                
    # Legacy support
    # =========================================================
    if hasattr(action, 'fcurves'):
        fcurves.extend(list(action.fcurves))
        
    for fc in fcurves:
        if fc.data_path in (path_x, path_y):
            axis = 'x' if fc.data_path == path_x else 'y'
            for kp in fc.keyframe_points:
                fr = round(kp.co[0])
                if fr not in uv_data:
                    uv_data[fr] = {'x': 0.0, 'y': 0.0, 'interp': 'linear'}
                
                uv_data[fr][axis] = kp.co[1]
                
                if kp.interpolation == 'CONSTANT': # Blockbench use step
                    uv_data[fr]['interp'] = 'step'
                    
    shape_uv_offset = []
    for fr in sorted(uv_data.keys()):
        shape_uv_offset.append({
            "time": int((fr * fps_factor) + 0.5),
            "delta": {
                "x": int(uv_data[fr]['x']),
                "y": -int(uv_data[fr]['y'])
            },
            "interpolationType": uv_data[fr]['interp']
        })
        
    return shape_uv_offset

def extract_bone_name(fcurve, obj):
    """Extracts the bone name from an fcurve data path."""
    data_path = fcurve.data_path
    
    if 'pose.bones["' in data_path:
        try:
            return data_path.split('"')[1]
        except IndexError:
            pass
    elif 'bones["' in data_path:
        try:
            return data_path.split('"')[1]
        except IndexError:
            pass

    if hasattr(fcurve, "group") and fcurve.group and fcurve.group.name in obj.pose.bones:
        return fcurve.group.name
        
    slot = getattr(fcurve, "slot", None)
    if slot and hasattr(slot, "name") and slot.name in obj.pose.bones:
        return slot.name
        
    return None

def get_bone_keyframes(action, obj):
    """Scans the action for all transform, visibility, and UV keyframes associated with bones."""
    bone_pos_keyframes = {}
    bone_rot_keyframes = {}
    bone_scale_keyframes = {}
    bone_hide_keyframes = {}
    bone_uv_keyframes = {}
    collected_fcurves = []
    
    def deep_scan(item, depth=0):
        # Recursively collects fcurves
        if depth > 5 or item is None:
            return
        
        if hasattr(item, "fcurves"):
            try:
                for fc in item.fcurves:
                    if fc not in collected_fcurves:
                        collected_fcurves.append(fc)
            except Exception:
                pass
        
        for attr in dir(item):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(item, attr)
                if isinstance(val, (bpy.types.bpy_prop_collection, list, tuple)):
                    for sub_item in val:
                        deep_scan(sub_item, depth + 1)
                elif hasattr(val, "fcurves") or hasattr(val, "layers") or hasattr(val, "strips") or hasattr(val, "action"):
                    deep_scan(val, depth + 1)
            except Exception:
                pass

    deep_scan(action)

    for fcurve in collected_fcurves:
        bone_name = extract_bone_name(fcurve, obj)

        if not bone_name or bone_name not in obj.pose.bones:
            continue
            
        if bone_name.endswith("_Global_Location"):
            continue

        prop_name = fcurve.data_path.rsplit('.', 1)[-1]
        prop_path_lower = fcurve.data_path.lower()
        frames = {int(round(kp.co.x)) for kp in fcurve.keyframe_points if hasattr(kp, "co")}

        if "location" in prop_name or "translation" in prop_name:
            if bone_name not in bone_pos_keyframes:
                bone_pos_keyframes[bone_name] = set()
            bone_pos_keyframes[bone_name].update(frames)

        elif "rotation" in prop_name or "quaternion" in prop_name or "euler" in prop_name:
            if bone_name not in bone_rot_keyframes:
                bone_rot_keyframes[bone_name] = set()
            bone_rot_keyframes[bone_name].update(frames)
            
        elif "scale" in prop_name:
            if bone_name not in bone_scale_keyframes:
                bone_scale_keyframes[bone_name] = set()
            bone_scale_keyframes[bone_name].update(frames)
            
        elif "hide" in prop_name or "hide" in prop_path_lower: 
            if bone_name not in bone_hide_keyframes:
                bone_hide_keyframes[bone_name] = set()
            bone_hide_keyframes[bone_name].update(frames)
            
        elif "shapeuvoffset" in prop_path_lower:
            if bone_name not in bone_uv_keyframes:
                bone_uv_keyframes[bone_name] = set()
            bone_uv_keyframes[bone_name].update(frames)

    return bone_pos_keyframes, bone_rot_keyframes, bone_scale_keyframes, bone_hide_keyframes, bone_uv_keyframes

def setup_global_location_bones(obj):
    """Creates temporary bones to extract absolute global locations during bake."""
    COLLECTION_NAME = "Bone_Global_location"
    SUFFIX = "_Global_Location"
    BONE_LENGTH = 1.0  

    original_mode = obj.mode
    bpy.ops.object.mode_set(mode='EDIT')

    arm = obj.data
    collection = arm.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = arm.collections.new(COLLECTION_NAME)

    created = []

    bones_to_process = [
        b for b in arm.edit_bones 
        if not b.name.endswith(SUFFIX) and not b.name.endswith("_Config")
    ]

    for bone in bones_to_process:
        new_name = bone.name + SUFFIX
        new_bone = arm.edit_bones.get(new_name)
        
        if new_bone is None:
            new_bone = arm.edit_bones.new(new_name)
            new_bone.head = bone.head.copy()

            if bone.parent:
                direction = (bone.parent.tail - bone.parent.head).normalized()
                if direction.length == 0:
                    direction = Vector((0, 0, 1.0))

                new_bone.tail = new_bone.head + (direction * BONE_LENGTH)
                new_bone.roll = bone.parent.roll
                new_bone.parent = bone.parent
                new_bone.use_connect = False
            else:
                new_bone.tail = bone.head + Vector((0, 0, BONE_LENGTH))
                new_bone.roll = 0
                new_bone.parent = None

        collection.assign(new_bone)
        created.append((new_name, bone.name))

    bpy.ops.object.mode_set(mode='POSE')

    for new_name, source_name in created:
        pose_bone = obj.pose.bones.get(new_name)
        if pose_bone:
            exists = any(
                c.type == 'COPY_LOCATION' and c.subtarget == source_name
                for c in pose_bone.constraints
            )

            if not exists:
                c = pose_bone.constraints.new('COPY_LOCATION')
                c.name = "Copy Location"
                c.target = obj
                c.subtarget = source_name

    if original_mode != 'POSE':
        try:
            bpy.ops.object.mode_set(mode=original_mode)
        except Exception:
            pass

def clean_baked_action_channels(action, original_channels, static_poses):
    """External filter to clean bake noise by removing non-existent channels and filtering valid frames."""
    if not action:
        return
        
    def optimize_fcurves(item, depth=0):
        # Recursively processes fcurves
        if depth > 5 or item is None: return
        
        if hasattr(item, "fcurves"):
            fcurves_to_remove = []
            for fc in item.fcurves:
                if 'pose.bones["' in fc.data_path:
                    b_name = fc.data_path.split('"')[1]
                    
                    if b_name.endswith("_Global_Location"): # Ignore global bones
                        continue
                        
                    if b_name in static_poses: # Remove entire curve if bone was static
                        fcurves_to_remove.append(fc)
                    else:
                        channel_key = (fc.data_path, fc.array_index) # Verify specific channel footprint
                        
                        if channel_key not in original_channels: # Remove baked curve if empty in original
                            fcurves_to_remove.append(fc)
                        else:
                            valid_frames = original_channels[channel_key]
                            for i in range(len(fc.keyframe_points) - 1, -1, -1): # Iterate backwards to protect list
                                if round(fc.keyframe_points[i].co.x) not in valid_frames:
                                    fc.keyframe_points.remove(fc.keyframe_points[i])
                                    
            for fc in fcurves_to_remove: # Remove marked curves
                try: item.fcurves.remove(fc)
                except Exception: pass
                
        for attr in dir(item): # Recursive scan
            if attr.startswith("_"): continue
            try:
                val = getattr(item, attr)
                if isinstance(val, (bpy.types.bpy_prop_collection, list, tuple)):
                    for sub in val: optimize_fcurves(sub, depth + 1)
                elif hasattr(val, "fcurves") or hasattr(val, "layers") or hasattr(val, "strips") or hasattr(val, "channelbags"):
                    optimize_fcurves(val, depth + 1)
            except Exception: pass

    optimize_fcurves(action)

def enforce_keyframe_boundaries(original_channels, frame_max, frame_min=0):
    """Ensures out of bounds keyframes are anchored to limits."""
    for channel_key, frames in original_channels.items():
        if not frames:
            continue
            
        if any(f < frame_min for f in frames): # Create anchors at limits
            frames.add(frame_min)
            
        if any(f > frame_max for f in frames):
            frames.add(frame_max)
            
        out_of_bounds = {f for f in frames if f < frame_min or f > frame_max}
        for f in out_of_bounds:
            frames.remove(f)

def bake_and_optimize_rig(obj, context):
    """Bakes all bones explicitly cleaning the noise."""
    original_mode = obj.mode
    import logging
    logger = logging.getLogger(__name__)
    
    bpy.ops.object.mode_set(mode='POSE')
    action = obj.animation_data.action if obj.animation_data else None
    
    # Deep scan - Save original channels and keyframes
    # =========================================================
    original_channels = {} 
    animated_bones = set() 
    
    def scan_original_frames(item, depth=0):
        # Scans the action data
        if depth > 5 or item is None: return
        if hasattr(item, "fcurves"):
            for fc in item.fcurves:
                if 'pose.bones["' in fc.data_path:
                    b_name = fc.data_path.split('"')[1]
                    animated_bones.add(b_name)
                    
                    channel_key = (fc.data_path, fc.array_index)
                    if channel_key not in original_channels:
                        original_channels[channel_key] = set()
                        
                    for kp in fc.keyframe_points:
                        original_channels[channel_key].add(round(kp.co.x))
                        
        for attr in dir(item):
            if attr.startswith("_"): continue
            try:
                val = getattr(item, attr)
                if isinstance(val, (bpy.types.bpy_prop_collection, list, tuple)):
                    for sub in val: scan_original_frames(sub, depth + 1)
                elif hasattr(val, "fcurves") or hasattr(val, "layers") or hasattr(val, "strips") or hasattr(val, "channelbags"):
                    scan_original_frames(val, depth + 1)
            except Exception: pass

    if action:
        scan_original_frames(action)
        
    # Clamp keyframes strictly to export bounds
    # =========================================================
    frame_start = 0 
    frame_end = int(context.scene.frame_end)
    enforce_keyframe_boundaries(original_channels, frame_end, frame_start)
    
    # Save static bone matrices
    # =========================================================
    static_poses = {}
    for pbone in obj.pose.bones:
        if pbone.name not in animated_bones and not pbone.name.endswith("_Global_Location") and not pbone.name.endswith("_Config"):
            static_poses[pbone.name] = {
                "matrix": pbone.matrix_basis.copy(),
                "loc": pbone.location.copy(),
                "rot_q": pbone.rotation_quaternion.copy() if pbone.rotation_mode == 'QUATERNION' else None,
                "rot_e": pbone.rotation_euler.copy() if pbone.rotation_mode != 'QUATERNION' else None,
                "scale": pbone.scale.copy()
            }
            
    # Prepare selection for bake
    # =========================================================
    arm = obj.data
    bcol = arm.collections.get("Bone_Global_location")
    if bcol and hasattr(bcol, "is_visible"):
        bcol.is_visible = True
        
    has_bones_to_bake = False
    for pbone in obj.pose.bones:
        if not pbone.name.endswith("_Config"): 
            if hasattr(pbone, "bone") and hasattr(pbone.bone, "hide"): pbone.bone.hide = False
            if hasattr(pbone, "hide"): pbone.hide = False
            if hasattr(pbone, "select"): pbone.select = True
            if hasattr(pbone, "bone") and hasattr(pbone.bone, "select"): pbone.bone.select = True
            has_bones_to_bake = True

    if not has_bones_to_bake:
        return
        
    # Global bake
    # =========================================================
    try:
        window = context.window
        screen = window.screen
        area = next((a for a in screen.areas if a.type == 'VIEW_3D'), None)
        region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None

        if area:
            with context.temp_override(window=window, screen=screen, area=area, region=region, active_object=obj, object=obj):
                bpy.ops.nla.bake(frame_start=frame_start, frame_end=frame_end, only_selected=True, visual_keying=True, clear_constraints=True, use_current_action=True, bake_types={'POSE'})
        else:
            with context.temp_override(active_object=obj, object=obj):
                bpy.ops.nla.bake(frame_start=frame_start, frame_end=frame_end, only_selected=True, visual_keying=True, clear_constraints=True, use_current_action=True, bake_types={'POSE'})
    except RuntimeError as e:
        logger.error("Error during Bake: %s", e)
        
    # Post-bake clean
    # =========================================================
    baked_action = obj.animation_data.action if obj.animation_data else None
    if baked_action:
        clean_baked_action_channels(baked_action, original_channels, static_poses)
        
    # Restore static bone poses and clean up
    # =========================================================
    for b_name, pose in static_poses.items():
        pbone = obj.pose.bones.get(b_name)
        if pbone:
            pbone.matrix_basis = pose["matrix"]
            pbone.location = pose["loc"]
            if pose["rot_q"]: pbone.rotation_quaternion = pose["rot_q"]
            if pose["rot_e"]: pbone.rotation_euler = pose["rot_e"]
            pbone.scale = pose["scale"]
            
    for pbone in obj.pose.bones:
        if hasattr(pbone, "select"): pbone.select = False
        if hasattr(pbone, "bone") and hasattr(pbone.bone, "select"): pbone.bone.select = False
        
    if original_mode != 'POSE':
        try: bpy.ops.object.mode_set(mode=original_mode)
        except Exception: pass
        
def cleanup_global_location_bones(obj, action):
    """Removes temporary global location bones and their associated animation data."""
    original_mode = obj.mode
    
    # cleanup of F Curves and groups
    # =========================================================
    def recursive_cleanup(item, depth=0):
        if depth > 5 or item is None:
            return
            
        if hasattr(item, "fcurves"):
            try:
                fcurves_to_remove = [fc for fc in item.fcurves if "_Global_Location" in fc.data_path]
                for fc in fcurves_to_remove:
                    item.fcurves.remove(fc)
            except Exception:
                pass
                
        if hasattr(item, "groups"):
            try:
                groups_to_remove = [g for g in item.groups if g.name.endswith("_Global_Location")]
                for g in groups_to_remove:
                    item.groups.remove(g)
            except Exception:
                pass
                
        for attr in dir(item):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(item, attr)
                if isinstance(val, (bpy.types.bpy_prop_collection, list, tuple)):
                    for sub_item in val:
                        recursive_cleanup(sub_item, depth + 1)
                elif hasattr(val, "fcurves") or hasattr(val, "layers") or hasattr(val, "strips") or hasattr(val, "action") or hasattr(val, "slots"):
                    recursive_cleanup(val, depth + 1)
            except Exception:
                pass

    if action:
        recursive_cleanup(action)

    # Switch to EDIT mode to remove physical bones
    # =========================================================
    try:
        bpy.ops.object.mode_set(mode='EDIT')
    except RuntimeError:
        return

    arm = obj.data
    
    bones_to_remove = [b.name for b in arm.edit_bones if b.name.endswith("_Global_Location")]
    
    for b_name in bones_to_remove:
        eb = arm.edit_bones.get(b_name)
        if eb:
            arm.edit_bones.remove(eb)
            
    bcol = arm.collections.get("Bone_Global_location")
    if bcol:
        try:
            arm.collections.remove(bcol)
        except Exception:
            pass
            
    if original_mode != 'EDIT':
        try:
            bpy.ops.object.mode_set(mode=original_mode)
        except Exception:
            pass

def export_blockyanim(filepath, context, target_rig, operator_ref=None):
    """Main export pipeline - duplicates rig, bakes animations, extracts data, and export blockyanim."""
    if operator_ref:
        operator_ref.report({'INFO'}, f"Processing export for {target_rig.name}...")
        
    original_rig = target_rig if target_rig else context.active_object
    if not original_rig or original_rig.type != 'ARMATURE':
        if operator_ref:
            operator_ref.report({'ERROR'}, "Select a valid rig (Armature) to export.")
        return {'CANCELLED'}

    action = context.scene.export_action
    
    if not action:
        if original_rig.animation_data and original_rig.animation_data.action:
            action = original_rig.animation_data.action
        else:
            if operator_ref:
                operator_ref.report({'ERROR'}, "Select an action in the panel before exporting.")
            return {'CANCELLED'}

    # Preparation and cloning
    # =========================================================
    current_frame = context.scene.frame_current
    
    if context.active_object and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
        
    bpy.ops.object.select_all(action='DESELECT')
    original_rig.select_set(True)
    context.view_layer.objects.active = original_rig

    bpy.ops.object.duplicate(linked=False)
    export_rig = context.active_object
    export_rig.name = original_rig.name + "_Export_Temp"
    
    auto_cloned_action = None # Capture garbage action auto-cloned by Blender
    if export_rig.animation_data and export_rig.animation_data.action:
        if export_rig.animation_data.action != action:
            auto_cloned_action = export_rig.animation_data.action
            
    original_rig.hide_viewport = True
    temp_action = None

    try:
        # Safe workspace working only on clone
        # =========================================================
        bpy.ops.object.mode_set(mode='POSE')
        
        if not export_rig.animation_data:
            export_rig.animation_data_create()
            
        temp_action = action.copy()
        temp_action.name = action.name + "_TempBake"
        export_rig.animation_data.action = temp_action

        setup_global_location_bones(export_rig)
        bake_and_optimize_rig(export_rig, context)

        # Data extraction
        # =========================================================
        current_fps = context.scene.render.fps
        fps_factor = 60.0 / current_fps if current_fps > 0 else 1.0
        scene_end_frame = context.scene.frame_end
        
        blockyanim_data = {
            "formatVersion": 1, 
            "duration": int((scene_end_frame * fps_factor) + 0.5),
            "holdLastKeyframe": False,
            "nodeAnimations": {}
        }

        baked_action = export_rig.animation_data.action 
        bone_pos_keyframes, bone_rot_keyframes, bone_scale_keyframes, bone_hide_keyframes, bone_uv_keyframes = get_bone_keyframes(baked_action, export_rig)

        all_animated_bones = set(bone_pos_keyframes.keys()) | set(bone_rot_keyframes.keys()) | set(bone_scale_keyframes.keys()) | set(bone_hide_keyframes.keys()) | set(bone_uv_keyframes.keys())

        for pbone in export_rig.pose.bones:
            if pbone.bone.hide or ("hide" in pbone.keys() and pbone["hide"] > 0) or hasattr(pbone, "hide") and pbone.hide:
                all_animated_bones.add(pbone.name)

        if not all_animated_bones and operator_ref:
            operator_ref.report({'WARNING'}, "No valid keyframes found in the selected action.")

        all_unique_frames = set()
        valid_export_bones = []
        
        for bone_name in all_animated_bones:
            if bone_name.endswith("_Global_Location") or bone_name not in export_rig.pose.bones:
                continue
                
            valid_export_bones.append(bone_name)
            
            if bone_name in bone_pos_keyframes:
                all_unique_frames.update(bone_pos_keyframes[bone_name])
            if bone_name in bone_rot_keyframes:
                all_unique_frames.update(bone_rot_keyframes[bone_name])
            if bone_name in bone_scale_keyframes:
                all_unique_frames.update(bone_scale_keyframes[bone_name])
            if bone_name in bone_hide_keyframes: 
                all_unique_frames.update(bone_hide_keyframes[bone_name])

        if not all_unique_frames and valid_export_bones:
            all_unique_frames.add(int(context.scene.frame_start))

        all_unique_frames = sorted(list(all_unique_frames))

        for bone_name in valid_export_bones:
            blockyanim_data["nodeAnimations"][bone_name] = {
                "position": [],
                "orientation": [],
                "shapeStretch": [],
                "shapeVisible": [],
                "shapeUvOffset": get_bone_uv_keyframes(baked_action, bone_name, fps_factor)
            }

        last_visibility = {}

        for frame in all_unique_frames:
            context.scene.frame_set(frame) 
            absolute_time = int((frame * fps_factor) + 0.5)
            
            for bone_name in valid_export_bones:
                pbone = export_rig.pose.bones.get(bone_name)
                
                is_hidden = False
                if "hide" in pbone.keys():
                    is_hidden = bool(pbone["hide"])
                elif hasattr(pbone, "hide"): 
                    is_hidden = pbone.hide
                else:
                    is_hidden = pbone.bone.hide
                    
                current_vis = not is_hidden
                has_vis_anim = (bone_name in bone_hide_keyframes)
                
                # Only export hide keyframes
                if has_vis_anim or not current_vis:
                    if bone_name not in last_visibility or last_visibility[bone_name] != current_vis:
                        blockyanim_data["nodeAnimations"][bone_name]["shapeVisible"].append({
                            "time": absolute_time,
                            "delta": current_vis,
                            "interpolationType": "step"
                        })
                        last_visibility[bone_name] = current_vis
                        
                if bone_name in bone_pos_keyframes and frame in bone_pos_keyframes[bone_name]:
                    global_bone_name = bone_name + "_Global_Location"
                    global_pbone = export_rig.pose.bones.get(global_bone_name)
                    
                    if global_pbone:
                        loc = global_pbone.matrix_basis.translation
                    else:
                        loc = pbone.matrix_basis.translation

                    blockyanim_data["nodeAnimations"][bone_name]["position"].append({
                        "time": absolute_time,
                        "delta": clean_delta_decimals({"x": loc.x, "y": loc.y, "z": loc.z}),
                        "interpolationType": "linear"
                    })

                if bone_name in bone_rot_keyframes and frame in bone_rot_keyframes[bone_name]:
                    rot = pbone.matrix_basis.to_quaternion()
                    blockyanim_data["nodeAnimations"][bone_name]["orientation"].append({
                        "time": absolute_time,
                        "delta": clean_delta_decimals({"x": rot.x, "y": rot.y, "z": rot.z, "w": rot.w}, is_orientation=True),
                        "interpolationType": "linear"
                    })
                    
                if bone_name in bone_scale_keyframes and frame in bone_scale_keyframes[bone_name]:
                    scl = pbone.matrix_basis.to_scale()
                    blockyanim_data["nodeAnimations"][bone_name]["shapeStretch"].append({
                        "time": absolute_time,
                        "delta": clean_delta_decimals({"x": scl.x, "y": scl.y, "z": scl.z}),
                        "interpolationType": "linear"
                    })

        # File writing
        # =========================================================
        json_str = json.dumps(blockyanim_data, indent=2)
        json_str = re.sub(
            r'"delta":\s*\{\s*(.*?)\s*\}',
            lambda match: '"delta": {' + re.sub(r'\s+', ' ', match.group(1)).strip() + '}',
            json_str,
            flags=re.DOTALL
        )
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(json_str)
            
        if operator_ref:
            operator_ref.report({'INFO'}, f"Animation '{action.name}' exported securely.")

    except Exception as e:
        if operator_ref:
            operator_ref.report({'ERROR'}, f"Export Failed: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        # cleanup
        # =========================================================
        context.scene.frame_set(current_frame)

        if context.active_object and context.active_object.mode != 'OBJECT':
            try: bpy.ops.object.mode_set(mode='OBJECT')
            except Exception: pass
            
        if export_rig:
            export_rig_data = export_rig.data
            try: bpy.data.objects.remove(export_rig, do_unlink=True)
            except Exception: pass
            if export_rig_data:
                try: bpy.data.armatures.remove(export_rig_data, do_unlink=True)
                except Exception: pass
        
        if temp_action:
            try: bpy.data.actions.remove(temp_action, do_unlink=True)
            except Exception: pass
            
        if auto_cloned_action:
            try: bpy.data.actions.remove(auto_cloned_action, do_unlink=True)
            except Exception: pass
            
        if original_rig:
            original_rig.hide_viewport = False
            bpy.ops.object.select_all(action='DESELECT')
            original_rig.select_set(True)
            context.view_layer.objects.active = original_rig
            try: bpy.ops.object.mode_set(mode='POSE')
            except Exception: pass

    return {'FINISHED'}