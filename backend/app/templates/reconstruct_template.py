"""Reconstruct template — based on user's reconstruct_texture.py.

Run inside Blender on the scene saved by the render stage. All path/threshold
constants are placeholders that the backend replaces before execution.
"""
import bpy
import os
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.object_utils import world_to_camera_view

# ==================== 配置 (由后端注入) ====================
TARGET_OBJ_NAME = r"__TARGET_OBJ_NAME__"
INPUT_DIR = r"__INPUT_DIR__"
OUTPUT_DIR = r"__OUTPUT_DIR__"
TEX_SIZE = __TEX_SIZE__
CAM_NAMES = ["cam_front", "cam_back", "cam_lef", "cam_rig", "cam_top", "cam_bott"]
FINAL_NAME = r"__FINAL_NAME__"
INPAINT_ITERS = __INPAINT_ITERS__
SEAM_DILATE = __SEAM_DILATE__
WEAR_INTENSITY = __WEAR_INTENSITY__   # 0-100, 控制后处理阈值+膨胀
FACING_MIN = __FACING_MIN__
OCCLUSION_REL = __OCCLUSION_REL__
SAVE_DEBUG = __SAVE_DEBUG__
# =========================================================


def get_view_path(cam_name):
    return os.path.join(bpy.path.abspath(INPUT_DIR), f"view_{cam_name}_wear_mask.png")


def project_from_view(obj, cam):
    scene = bpy.context.scene
    scene.camera = cam
    uv = obj.data.uv_layers.new(name="ProjUV")
    obj.data.uv_layers.active = uv
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    win = bpy.context.window
    area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
    if area is None:
        raise RuntimeError("需要 3D 视口。请在常规界面运行 (非 background 模式)。")
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    space = area.spaces.active
    with bpy.context.temp_override(window=win, area=area, region=region):
        space.region_3d.view_perspective = 'CAMERA'
        bpy.ops.uv.project_from_view(
            orthographic=False, camera_bounds=True,
            correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    return uv.name


def make_color_bake_material(view_img_path, proj_uv_name):
    img = bpy.data.images.load(view_img_path, check_existing=True)
    img.colorspace_settings.name = 'Non-Color'
    mat = bpy.data.materials.new(name="ColorBakeMat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    emit = nt.nodes.new('ShaderNodeEmission')
    uvmap = nt.nodes.new('ShaderNodeUVMap')
    uvmap.uv_map = proj_uv_name
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    tex.extension = 'CLIP'
    nt.links.new(tex.inputs['Vector'], uvmap.outputs['UV'])
    nt.links.new(emit.inputs['Color'], tex.outputs['Color'])
    nt.links.new(out.inputs['Surface'], emit.outputs['Emission'])
    return mat, img


def bake_color(obj, cam, view_img_path, tex_size):
    scene = bpy.context.scene
    proj_uv = project_from_view(obj, cam)
    orig_uv = None
    for uvl in obj.data.uv_layers:
        if uvl.name != proj_uv:
            orig_uv = uvl
            break

    bake_img = bpy.data.images.new(f"colorbake_{cam.name}",
                                   width=tex_size, height=tex_size, alpha=True)
    bake_img.generated_color = (0, 0, 0, 0)
    mat, vimg = make_color_bake_material(view_img_path, proj_uv)
    nt = mat.node_tree
    bake_target = nt.nodes.new('ShaderNodeTexImage')
    bake_target.image = bake_img
    bake_target.select = True
    nt.nodes.active = bake_target

    orig_mats = [s.material for s in obj.material_slots]
    if not obj.material_slots:
        obj.data.materials.append(mat)
    else:
        for s in obj.material_slots:
            s.material = mat

    obj.data.uv_layers.active = orig_uv
    scene.render.bake.use_clear = True
    scene.render.bake.margin = 16   # 16px 岛边缘溢出,防接缝断裂
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    print(f"[bake] {cam.name}")
    bpy.ops.object.bake(type='EMIT')

    px = np.array(bake_img.pixels[:], dtype=np.float32).reshape(tex_size, tex_size, 4)
    color = px[..., :3].copy()
    bake_alpha = (px[..., 3] > 0.001).astype(np.float32)

    for s, m in zip(obj.material_slots, orig_mats):
        s.material = m
    bpy.data.materials.remove(mat)
    bpy.data.images.remove(bake_img)
    proj = obj.data.uv_layers.get(proj_uv)
    if proj:
        obj.data.uv_layers.remove(proj)
    return color, bake_alpha


def build_bvh(depsgraph, obj):
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    verts = [obj_eval.matrix_world @ v.co for v in mesh.vertices]
    polys = [list(p.vertices[:]) for p in mesh.polygons]
    bvh = BVHTree.FromPolygons(verts, polys)
    obj_eval.to_mesh_clear()
    return bvh


def compute_weight_map(obj, cam, bvh, tex_size):
    scene = bpy.context.scene
    mesh = obj.data
    uv_layer = mesh.uv_layers.active.data
    mw = obj.matrix_world
    mesh.calc_loop_triangles()
    world_co = [mw @ v.co for v in mesh.vertices]
    weight = np.zeros((tex_size, tex_size), dtype=np.float32)
    cam_loc = cam.matrix_world.translation

    for tri in mesh.loop_triangles:
        l0, l1, l2 = tri.loops
        vi = tri.vertices
        uv0 = uv_layer[l0].uv; uv1 = uv_layer[l1].uv; uv2 = uv_layer[l2].uv
        p0 = Vector(world_co[vi[0]]); p1 = Vector(world_co[vi[1]]); p2 = Vector(world_co[vi[2]])
        fn = (mw.to_3x3() @ tri.normal).normalized()
        a = np.array([uv0[0]*tex_size, uv0[1]*tex_size])
        b = np.array([uv1[0]*tex_size, uv1[1]*tex_size])
        c = np.array([uv2[0]*tex_size, uv2[1]*tex_size])
        minx = max(int(np.floor(min(a[0], b[0], c[0]))), 0)
        maxx = min(int(np.ceil(max(a[0], b[0], c[0]))), tex_size-1)
        miny = max(int(np.floor(min(a[1], b[1], c[1]))), 0)
        maxy = min(int(np.ceil(max(a[1], b[1], c[1]))), tex_size-1)
        if minx > maxx or miny > maxy:
            continue
        def edge(va, vb, vp):
            return (vb[0]-va[0])*(vp[1]-va[1]) - (vb[1]-va[1])*(vp[0]-va[0])
        area = edge(a, b, c)
        if abs(area) < 1e-9:
            continue
        for py in range(miny, maxy+1):
            for px_ in range(minx, maxx+1):
                ppx = np.array([px_+0.5, py+0.5])
                w0 = edge(b, c, ppx)/area
                w1 = edge(c, a, ppx)/area
                w2 = edge(a, b, ppx)/area
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                wpos = p0*w0 + p1*w1 + p2*w2
                cu, cv, cz = world_to_camera_view(scene, cam, wpos)
                if cz <= 0 or cu < 0 or cu > 1 or cv < 0 or cv > 1:
                    continue
                view_dir = (wpos - cam_loc).normalized()
                facing = -view_dir.dot(fn)
                if facing <= FACING_MIN:
                    continue
                direction = wpos - cam_loc
                dist = direction.length
                hit, hloc, hn, hidx = bvh.ray_cast(cam_loc, direction.normalized(), dist)
                if hit and (hloc - cam_loc).length < dist * OCCLUSION_REL:
                    continue
                weight[py, px_] = facing ** 2
    return weight


def composite(color_weight_list, tex_size):
    accum = np.zeros((tex_size, tex_size, 3), dtype=np.float64)
    wsum = np.zeros((tex_size, tex_size), dtype=np.float64)
    for color, bake_alpha, weight in color_weight_list:
        w = weight * bake_alpha
        for c in range(3):
            accum[..., c] += color[..., c] * w
        wsum += w
    mask = wsum > 1e-6
    out = np.zeros((tex_size, tex_size, 4), dtype=np.float32)
    for c in range(3):
        ch = np.zeros((tex_size, tex_size))
        ch[mask] = accum[..., c][mask] / wsum[mask]
        out[..., c] = ch
    out[..., 3] = mask.astype(np.float32)
    out[..., 3] = (out[..., 3] > 0).astype(np.float32)
    return out


def morph_close(alpha):
    a = alpha.copy()
    for _ in range(2):
        a = np.maximum(a, np.roll(a, 1, 0))
        a = np.maximum(a, np.roll(a, -1, 0))
        a = np.maximum(a, np.roll(a, 1, 1))
        a = np.maximum(a, np.roll(a, -1, 1))
    return a


def inpaint_dilate(out, iterations):
    rgb = out[..., :3].copy()
    alpha = out[..., 3].copy()
    for _ in range(iterations):
        empty = alpha < 0.5
        if not empty.any():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros_like(alpha)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                sr = np.roll(np.roll(rgb, dy, 0), dx, 1)
                sa = np.roll(np.roll(alpha, dy, 0), dx, 1)
                m = (sa > 0.5)
                acc += sr * m[..., None]
                cnt += m
        fillable = empty & (cnt > 0)
        for c in range(3):
            rgb[..., c][fillable] = acc[..., c][fillable] / cnt[fillable]
        alpha[fillable] = 1.0
    out[..., :3] = rgb
    out[..., 3] = 1.0
    return out


def median_filter(arr, size=3, iterations=1):
    out = arr.copy()
    r = size // 2
    offsets = [(dy, dx) for dy in range(-r, r + 1) for dx in range(-r, r + 1)]
    for _ in range(iterations):
        for c in range(3):
            chan = out[..., c]
            stack = [np.roll(np.roll(chan, dy, 0), dx, 1) for dy, dx in offsets]
            out[..., c] = np.median(np.stack(stack, axis=0), axis=0)
    return out


def invert_rgb(arr):
    out = arr.copy()
    out[..., :3] = 1.0 - out[..., :3]
    return out


def dilate_seam(arr, margin=8):
    """UV 接缝渗色: 把有色像素沿各方向向外扩张 margin 像素。

    多视角合成后,不同 UV 岛边界会留下未填充的空隙 → 接缝。
    把岛内颜色向外“渗血”填满这些空隙,覆盖接缝断裂。
    只填空白区,不改动已有颜色。
    """
    rgb = arr[..., :3].copy()
    alpha = arr[..., 3].copy()
    for _ in range(margin):
        empty = alpha < 0.5
        if not empty.any():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros_like(alpha)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                sr = np.roll(np.roll(rgb, dy, 0), dx, 1)
                sa = np.roll(np.roll(alpha, dy, 0), dx, 1)
                m = (sa > 0.5)
                acc += sr * m[..., None]
                cnt += m
        fillable = empty & (cnt > 0)
        for c in range(3):
            rgb[..., c][fillable] = acc[..., c][fillable] / cnt[fillable]
        alpha[fillable] = 1.0
    out = arr.copy()
    out[..., :3] = rgb
    out[..., 3] = alpha
    return out


def save_img(arr, name, tex_size):
    img = bpy.data.images.new(name, width=tex_size, height=tex_size, alpha=True)
    img.colorspace_settings.name = 'Non-Color'
    img.pixels = arr.flatten().tolist()
    p = os.path.join(bpy.path.abspath(OUTPUT_DIR), f"{name}.png")
    img.filepath_raw = p
    img.file_format = 'PNG'
    img.save()
    print(f"[save] {p}")
    bpy.data.images.remove(img)


def remove_scatter(arr, min_cluster=5):
    """形态学开运算去孤立噪点。先腐蚀再膨胀,滤掉小散点。

    优先用 scipy, 没有则用纯 numpy 实现。
    """
    try:
        from scipy.ndimage import binary_opening, generate_binary_structure
        alpha = arr[..., 3] > 0.01
        struct = generate_binary_structure(2, 1)
        opened = binary_opening(alpha, structure=struct, iterations=2)
        out = arr.copy()
        out[~opened, :3] = 0.0
        out[~opened, 3] = 0.0
        return out
    except ImportError:
        # NumPy fallback: 简单的腐蚀→膨胀
        alpha = arr[..., 3] > 0.01
        kernel_size = 3
        r = kernel_size // 2
        # 腐蚀
        eroded = alpha.copy()
        for _ in range(2):
            eroded = alpha.copy()
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    eroded = eroded & np.roll(np.roll(alpha, dy, 0), dx, 1)
            alpha = eroded
        # 膨胀
        for _ in range(2):
            eroded = alpha.copy()
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    eroded = eroded | np.roll(np.roll(alpha, dy, 0), dx, 1)
            alpha = eroded
        out = arr.copy()
        out[~alpha, :3] = 0.0
        out[~alpha, 3] = 0.0
        return out


def apply_wear_intensity(arr, intensity):
    """方案 B 轨: 用 intensity(0-100) 控制磨损遮罩的保留阈值和边缘膨胀。

    intensity 低 → 高阈值,只保留差分最强的区域 (轻微磨损)
    intensity 高 → 低阈值,保留更多灰度区域 + 额外膨胀 (重度磨损)
    """
    t = max(0, min(100, intensity)) / 100.0          # 归一化到 0-1
    # 阈值: intensity=0 → 0.80; intensity=100 → 0.10
    threshold = 0.80 - t * 0.70
    # 膨胀次数: intensity=0 → 0次; intensity=100 → 6次
    dilate_iters = int(round(t * 6))

    out = arr.copy()
    # 把 alpha 低于阈值的像素裁掉 (清除弱差分)
    weak = out[..., 3] < threshold
    out[weak, :3] = 0.0
    out[weak, 3] = 0.0

    # 高强度时膨胀边缘,让磨损区域向外扩张
    if dilate_iters > 0:
        alpha = out[..., 3].copy()
        rgb = out[..., :3].copy()
        for _ in range(dilate_iters):
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                nb_a = np.roll(np.roll(alpha, dy, 0), dx, 1)
                nb_rgb = np.roll(np.roll(rgb, dy, 0), dx, 1)
                grow = (alpha < 0.5) & (nb_a > 0.5)
                rgb[grow] = nb_rgb[grow]
                alpha[grow] = 1.0
        out[..., :3] = rgb
        out[..., 3] = alpha
    return out


def apply_black_background(arr):
    """透明区域填黑色,alpha 通道设为 1.0。"""
    out = arr.copy()
    transparent = out[..., 3] < 0.01
    out[transparent, :3] = 0.0
    out[transparent, 3] = 1.0
    out[..., 3] = 1.0  # 全部不透明
    return out


def ensure_uvs(obj):
    """如果模型没有 UV, 自动展开为横条排列。"""
    mesh = obj.data
    if mesh.uv_layers and len(mesh.uv_layers) > 0:
        print(f"[uv] 已有 {len(mesh.uv_layers)} 个 UV 层, 跳过展开")
        return

    print("[uv] 模型无 UV, 自动 Smart UV 展开 + 横条排列 ...")
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')

    # Smart UV Project: 角度限制低 → 碎片少; island margin 给一点间隙
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.005)
    bpy.ops.uv.average_islands_scale()

    # 横条排列: 按面积排序后 pack, 保证 UV 利用率高
    bpy.ops.uv.pack_islands(margin=0.005, rotate=True)

    bpy.ops.object.mode_set(mode='OBJECT')
    print(f"[uv] UV 展开完成, 当前 UV 层: {[u.name for u in mesh.uv_layers]}")


def main():
    obj = bpy.data.objects.get(TARGET_OBJ_NAME)
    if not obj:
        raise RuntimeError(f"找不到模型: {TARGET_OBJ_NAME}")

    bpy.context.scene.render.engine = 'CYCLES'
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='OBJECT')

    # 自动 UV 展开 (如果模型没有 UV 信息)
    ensure_uvs(obj)

    cam_objs = [bpy.data.objects.get(n) for n in CAM_NAMES]
    cam_objs = [c for c in cam_objs if c and c.type == 'CAMERA']
    print(f"参与相机: {[c.name for c in cam_objs]}")
    os.makedirs(bpy.path.abspath(OUTPUT_DIR), exist_ok=True)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = build_bvh(depsgraph, obj)

    results = []
    for cam in cam_objs:
        view_path = get_view_path(cam.name)
        if not os.path.exists(view_path):
            print(f"[skip] missing view: {view_path}")
            continue
        color, bake_alpha = bake_color(obj, cam, view_path, TEX_SIZE)
        obj.data.uv_layers.active = obj.data.uv_layers[0]
        print(f"[weight] {cam.name}")
        weight = compute_weight_map(obj, cam, bvh, TEX_SIZE)
        results.append((color, bake_alpha, weight))

        if SAVE_DEBUG:
            dbg = np.zeros((TEX_SIZE, TEX_SIZE, 4), dtype=np.float32)
            dbg[..., :3] = color; dbg[..., 3] = 1.0
            save_img(dbg, f"dbg_color_{cam.name}", TEX_SIZE)
            wdbg = np.zeros((TEX_SIZE, TEX_SIZE, 4), dtype=np.float32)
            wv = weight * bake_alpha
            for c in range(3):
                wdbg[..., c] = wv
            wdbg[..., 3] = 1.0
            save_img(wdbg, f"dbg_weight_{cam.name}", TEX_SIZE)

    if not results:
        raise RuntimeError("没有任何可用视角图")

    out = composite(results, TEX_SIZE)
    out[..., 3] = morph_close(out[..., 3])
    out = inpaint_dilate(out, iterations=INPAINT_ITERS)

    # ---- 去散点: 中值滤波 + 形态学开运算 ----
    out = median_filter(out, size=5, iterations=3)
    out = remove_scatter(out, min_cluster=5)

    # ---- 磨损强度后处理 (方案 B 轨) ----
    out = apply_wear_intensity(out, WEAR_INTENSITY)

    # ---- UV 接缝处理 ----
    if SAVE_DEBUG:
        save_img(out.copy(), "dbg_seam_before", TEX_SIZE)  # 接缝处理前
    out = dilate_seam(out, margin=SEAM_DILATE)
    if SAVE_DEBUG:
        save_img(out.copy(), "dbg_seam_after", TEX_SIZE)   # 接缝处理后

    # ---- 不反相, 保留原始颜色 ----

    # ---- 透明区填黑色底 ----
    out = apply_black_background(out)

    save_img(out, FINAL_NAME, TEX_SIZE)

    # ---- 导出带贴图的 GLB ----
    try:
        final_png = os.path.join(bpy.path.abspath(OUTPUT_DIR), f"{FINAL_NAME}.png")
        glb_path   = os.path.join(bpy.path.abspath(OUTPUT_DIR), f"{FINAL_NAME}.glb")

        # 建立最终材质(Principled BSDF + 贴图)
        mat = bpy.data.materials.new(name="WearResult")
        mat.use_nodes = True
        nt = mat.node_tree
        nt.nodes.clear()
        out_node = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf     = nt.nodes.new("ShaderNodeBsdfPrincipled")
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = bpy.data.images.load(final_png, check_existing=True)
        nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(bsdf.outputs["BSDF"],      out_node.inputs["Surface"])

        # 把材质赋给目标对象
        obj2 = bpy.data.objects.get(TARGET_OBJ_NAME)
        if obj2:
            obj2.data.materials.clear()
            obj2.data.materials.append(mat)

        # 导出 GLB(embed 贴图)
        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format="GLB",
            use_selection=False,
            export_image_format="PNG",
            export_texcoords=True,
            export_normals=True,
            export_materials="EXPORT",
        )
        print(f"[glb] exported → {glb_path}")
    except Exception as e:
        print(f"[glb] export failed (non-fatal): {e}")

    print("[done]")


try:
    main()
except Exception as exc:
    import traceback
    traceback.print_exc()
    print(f"[fatal] {exc}")
finally:
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        pass
