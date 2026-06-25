"""Render template — based on user's render.py.

Top-level constants are placeholders that the backend replaces before execution.
At the end the scene is saved as `__SCENE_BLEND_PATH__` so the reconstruct
stage can reuse it (Object_2 + 6 cameras).
"""
import bpy
import os
import math
import sys
from mathutils import Vector

# ==================== 配置 (由后端注入) ====================
GLB_PATH = r"__GLB_PATH__"
OUTPUT_DIR = r"__OUTPUT_DIR__"
SAMPLES = __SAMPLES__
RENDER_RES = __RENDER_RES__
CAM_DISTANCE = __CAM_DISTANCE__
SCENE_BLEND_PATH = r"__SCENE_BLEND_PATH__"
# =========================================================


def clean_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for b in list(block):
            block.remove(b)


def import_glb(path):
    p = bpy.path.abspath(path)
    if not os.path.exists(p):
        raise RuntimeError(f"找不到文件: {p}")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p)
    return [o for o in bpy.data.objects if o not in before]


def normalize_objects(objs):
    mesh_objs = [o for o in objs if o.type == 'MESH']
    if not mesh_objs:
        raise RuntimeError("GLB 中没有网格物体")
    min_v = Vector((math.inf,) * 3)
    max_v = Vector((-math.inf,) * 3)
    for o in mesh_objs:
        for corner in o.bound_box:
            world = o.matrix_world @ Vector(corner)
            min_v = Vector(map(min, min_v, world))
            max_v = Vector(map(max, max_v, world))
    center = (min_v + max_v) / 2
    size = (max_v - min_v)
    max_dim = max(size.x, size.y, size.z)
    scale = 1.0 / max_dim if max_dim > 0 else 1.0

    empty = bpy.data.objects.new("ModelRoot", None)
    bpy.context.collection.objects.link(empty)
    for o in objs:
        if o.parent is None:
            o.parent = empty
    empty.location = -center * scale
    empty.scale = (scale, scale, scale)
    bpy.context.view_layer.update()

    # 把第一个 mesh 重命名为 Object_2 (重建脚本需要的名字)
    if mesh_objs:
        mesh_objs[0].name = "Object_2"
    return Vector((0, 0, 0)), 0.5


def create_camera(name, location, target):
    cam_data = bpy.data.cameras.new(name)
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = location
    direction = (target - Vector(location))
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return cam


def create_cameras(center, radius):
    d = CAM_DISTANCE
    defs = {
        "cam_front": (0, -d, 0),
        "cam_back":  (0,  d, 0),
        "cam_lef":   (-d, 0, 0),
        "cam_rig":   (d,  0, 0),
        "cam_top":   (0,  0, d),
        "cam_bott":  (0,  0, -d),
    }
    return [create_camera(name, center + Vector(off), center) for name, off in defs.items()]


def create_lights(center):
    positions = [
        ("key",  (4, -4, 5), 1000),
        ("fill", (-4, -2, 3), 500),
        ("back", (0, 5, 4), 600),
    ]
    for name, loc, power in positions:
        ld = bpy.data.lights.new(name, type='AREA')
        ld.energy = power
        ld.size = 5
        light = bpy.data.objects.new(name, ld)
        light.location = Vector(loc) + center
        bpy.context.collection.objects.link(light)
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[1].default_value = 0.3


def setup_render():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = SAMPLES
    scene.render.resolution_x = RENDER_RES
    scene.render.resolution_y = RENDER_RES
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'


def render_all_views(cam_objs, outdir):
    scene = bpy.context.scene
    out_abs = bpy.path.abspath(outdir)
    os.makedirs(out_abs, exist_ok=True)
    rendered = {}
    for cam in cam_objs:
        scene.camera = cam
        fp = os.path.join(out_abs, f"view_{cam.name}.png")
        scene.render.filepath = fp
        print(f"[render] {cam.name} -> {fp}")
        bpy.ops.render.render(write_still=True)
        rendered[cam.name] = fp
    return rendered


def main():
    clean_scene()
    objs = import_glb(GLB_PATH)
    center, radius = normalize_objects(objs)
    cams = create_cameras(center, radius)
    create_lights(center)
    setup_render()
    rendered = render_all_views(cams, OUTPUT_DIR)

    print("[render done]")
    for name, path in rendered.items():
        print(f"  {name}: {path}")

    if SCENE_BLEND_PATH:
        bpy.ops.wm.save_as_mainfile(filepath=SCENE_BLEND_PATH)
        print(f"[scene saved] {SCENE_BLEND_PATH}")


main()
