"""Blender 侧：贴图图集、材质、区块网格对象、相机、选择框。"""
from __future__ import annotations

import math
import os
import tempfile

import bpy
import numpy as np

from . import mc_blocks as B
from .mc_const import (ATLAS_PX, CHUNK_X, CHUNK_Z, FAR_CLIP, FOV, NEAR_CLIP,
                       WORLD_H)
from .mc_textures import build_atlas

ATLAS_NAME = "MC_Atlas"
ATLAS_CACHE = "mc_atlas_cache.png"


# --------------------------------------------------------------------------
# 图集
# --------------------------------------------------------------------------
def ensure_atlas(seed: int = 20240501, dump_png: bool = False):
    """取得（必要时生成）贴图图集图像。"""
    img = bpy.data.images.get(ATLAS_NAME)
    if img is not None and tuple(img.size) == (ATLAS_PX, ATLAS_PX):
        return img
    if img is not None:
        bpy.data.images.remove(img)

    atlas = build_atlas(seed)
    img = bpy.data.images.new(ATLAS_NAME, ATLAS_PX, ATLAS_PX, alpha=True,
                              float_buffer=False)
    img.colorspace_settings.name = "sRGB"
    try:
        img.alpha_mode = "STRAIGHT"
    except (AttributeError, TypeError):
        pass
    # Blender 的像素缓冲是"从下到上"，这里翻转一下
    buf = (atlas[::-1].astype(np.float32) / 255.0)
    img.pixels.foreach_set(buf.ravel())
    img.pack()          # 存进 .blend，避免丢文件
    if dump_png:
        try:
            path = os.path.join(tempfile.gettempdir(), ATLAS_CACHE)
            img.filepath_raw = path
            img.file_format = "PNG"
            img.save()
        except Exception:
            pass
    return img


# --------------------------------------------------------------------------
# 材质
# --------------------------------------------------------------------------
def _set_input(node, index, name, value):
    try:
        sock = node.inputs[index]
    except (IndexError, TypeError):
        return None
    if value is not None:
        sock.default_value = value
    return sock


def _make_material(name, atlas, translucent):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (600, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.location = (-400, 150)
    tex.image = atlas
    try:
        tex.interpolation = "Closest"     # 像素风：不要模糊
    except TypeError:
        pass
    tex.extension = "CLIP"
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.location = (-400, -180)
    attr.attribute_name = "Shade"
    mul = nt.nodes.new("ShaderNodeVectorMath")
    mul.location = (-120, 0)
    mul.operation = "MULTIPLY"

    nt.links.new(tex.outputs["Color"], mul.inputs[0])
    nt.links.new(attr.outputs["Color"], mul.inputs[1])
    nt.links.new(mul.outputs["Vector"], bsdf.inputs[0])          # Base Color
    _set_input(bsdf, 2, "Roughness", 1.0)
    _set_input(bsdf, 1, "Metallic", 0.0)
    for nm in ("Specular IOR Level", "Specular"):
        if nm in bsdf.inputs:
            bsdf.inputs[nm].default_value = 0.0
            break
    if translucent:
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs[4])       # Alpha
        try:
            mat.blend_method = "BLEND"
        except TypeError:
            pass
        try:
            mat.surface_render_method = "BLENDED"
        except (AttributeError, TypeError):
            pass
        mat.use_backface_culling = False
    else:
        try:
            mat.blend_method = "OPAQUE"
        except TypeError:
            pass
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    mat.use_backface_culling = False
    # 视图着色（SOLID）+ 材质预览的背景用得到
    mat.diffuse_color = (0.55, 0.75, 0.45, 1.0) if not translucent else (0.35, 0.55, 0.9, 0.75)
    mat.roughness = 1.0
    return mat


def ensure_materials():
    atlas = ensure_atlas()
    solid = _make_material("MC_Solid", atlas, False)
    trans = _make_material("MC_Translucent", atlas, True)
    return solid, trans


# --------------------------------------------------------------------------
# 集合 / 场景
# --------------------------------------------------------------------------
def get_collection(name="MC_World"):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def clear_world_objects():
    for col_name in ("MC_World", "MC_Game"):
        col = bpy.data.collections.get(col_name)
        if col is None:
            continue
        for obj in list(col.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
                elif isinstance(data, bpy.types.Camera):
                    bpy.data.cameras.remove(data)
        bpy.data.collections.remove(col)


# --------------------------------------------------------------------------
# 区块网格
# --------------------------------------------------------------------------
def _fill_mesh(mesh, verts, faces, uvs, cols, mats):
    mesh.clear_geometry()
    n_v = len(verts)
    n_f = len(faces)
    if n_v == 0 or n_f == 0:
        return
    mesh.vertices.add(n_v)
    mesh.vertices.foreach_set("co", np.ascontiguousarray(verts, dtype=np.float32).ravel())
    mesh.loops.add(n_f * 4)
    mesh.loops.foreach_set("vertex_index",
                           np.ascontiguousarray(faces, dtype=np.int32).ravel())
    mesh.polygons.add(n_f)
    mesh.polygons.foreach_set("loop_start", np.arange(0, n_f * 4, 4, dtype=np.int32))
    mesh.polygons.foreach_set("loop_total", np.full(n_f, 4, dtype=np.int32))
    mesh.update(calc_edges=True)

    uvl = mesh.uv_layers.new(name="UVMap")
    uvl.data.foreach_set("uv", np.ascontiguousarray(uvs, dtype=np.float32).ravel())
    ca = mesh.color_attributes.new(name="Shade", type="FLOAT_COLOR", domain="CORNER")
    ca.data.foreach_set("color", np.ascontiguousarray(cols, dtype=np.float32).ravel())
    mesh.polygons.foreach_set("material_index",
                              np.ascontiguousarray(mats, dtype=np.int32))
    mesh.polygons.foreach_set("use_smooth", np.zeros(n_f, dtype=bool))
    mesh.update()


def build_chunk_object(cx, cz, data, mats, visible=True):
    """把 build_chunk_data 的结果写成一个 Blender 对象。"""
    col = get_collection("MC_World")
    name = f"MC_chunk_{cx}_{cz}"
    obj = bpy.data.objects.get(name)
    if obj is None:
        mesh = bpy.data.meshes.new(name)
        obj = bpy.data.objects.new(name, mesh)
        col.objects.link(obj)
        obj.display_type = "TEXTURED"
    mesh = obj.data
    if len(mesh.materials) != 2:
        mesh.materials.clear()
        mesh.materials.append(mats[0])
        mesh.materials.append(mats[1])
    if data is None:
        mesh.clear_geometry()
    else:
        verts, faces, uvs, cols, midx = data
        _fill_mesh(mesh, verts, faces, uvs, cols, midx)
    obj.location = (cx * CHUNK_X, cz * CHUNK_Z, 0.0)
    # 只在需要时改变可见性：每次写这两处都会让 Blender 重新求值整个场景
    want_hidden = not visible
    if obj.hide_viewport != want_hidden:
        obj.hide_viewport = want_hidden
    if obj.hide_render != want_hidden:
        obj.hide_render = want_hidden
    return obj


def remove_chunk_object(cx, cz):
    name = f"MC_chunk_{cx}_{cz}"
    obj = bpy.data.objects.get(name)
    if obj is None:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


# --------------------------------------------------------------------------
# 相机 / 选择框 / 光照
# --------------------------------------------------------------------------
def ensure_camera():
    obj = bpy.data.objects.get("MC_Camera")
    if obj is None:
        cam = bpy.data.cameras.new("MC_Camera")
        obj = bpy.data.objects.new("MC_Camera", cam)
        get_collection("MC_Game").objects.link(obj)
    cam = obj.data
    cam.lens_unit = "FOV"
    cam.angle = math.radians(FOV)
    cam.clip_start = NEAR_CLIP
    cam.clip_end = FAR_CLIP
    return obj


def ensure_selection_box():
    """Minecraft 的方块选中黑框。"""
    obj = bpy.data.objects.get("MC_Selection")
    if obj is None:
        # 只用 12 条棱构成线框立方体
        s = 1.0
        corners = [(0, 0, 0), (s, 0, 0), (s, 0, s), (0, 0, s),
                   (0, s, 0), (s, s, 0), (s, s, s), (0, s, s)]
        edges = [(0, 1), (1, 2), (2, 3), (3, 0),
                 (4, 5), (5, 6), (6, 7), (7, 4),
                 (0, 4), (1, 5), (2, 6), (3, 7)]
        mesh = bpy.data.meshes.new("MC_SelectionMesh")
        mesh.from_pydata(corners, edges, [])
        mesh.update()
        obj = bpy.data.objects.new("MC_Selection", mesh)
        get_collection("MC_Game").objects.link(obj)
        obj.color = (0.0, 0.0, 0.0, 1.0)
    obj.hide_viewport = True
    return obj


def ensure_world_lighting():
    """给 RENDERED / MATERIAL 预览提供一个天空色和太阳。"""
    scene = bpy.context.scene
    if scene.world is None:
        scene.world = bpy.data.worlds.new("MC_World")
    world = scene.world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs[0].default_value = (0.45, 0.62, 0.90, 1.0)   # 天空蓝
    bg.inputs[1].default_value = 1.0
    # 用渐变模拟天空更亮在上方
    nt.links.new(bg.outputs[0], out.inputs[0])

    if bpy.data.objects.get("MC_Sun") is None:
        light = bpy.data.lights.new("MC_Sun", type="SUN")
        light.energy = 3.0
        light.angle = math.radians(8.0)
        sun = bpy.data.objects.new("MC_Sun", light)
        get_collection("MC_Game").objects.link(sun)
        sun.rotation_euler = (math.radians(50), 0.0, math.radians(35))
    return world
