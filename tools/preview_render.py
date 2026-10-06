"""后台测试 / 预览渲染。

用法：
    blender --background --factory-startup --python tools/preview_render.py -- [搜索半径] [输出png] [种子]

1. 单元测试：单方块 6 面法线（验证绕序）；
2. 生成地形 → 建网格 → 统计；
3. 自动挑一处"有草有树有海"的取景点，用 Cycles 渲染预览图；
4. 导出贴图图集。
"""
from __future__ import annotations

import math
import os
import sys
import time

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_minecraft import mc_blocks as B                    # noqa: E402
from blender_minecraft import mc_mesher, mc_render, mc_world    # noqa: E402
from blender_minecraft.mc_const import SEA_LEVEL, WORLD_H       # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SEARCH = int(argv[0]) if argv else 4
OUT = argv[1] if len(argv) > 1 else os.path.join(ROOT, "preview.png")
SEED = int(argv[2]) if len(argv) > 2 else 20240501
VIEW_R = 3

print("=" * 60)
print(f"Blender {bpy.app.version_string}  搜索半径={SEARCH}  输出={OUT}  种子={SEED}")


# --------------------------------------------------------------------------
# 1. 单元测试
# --------------------------------------------------------------------------
def unit_test_normals():
    w = mc_world.World(seed=1)
    ch = w.get_chunk(0, 0)
    ch.blocks[:, :, :] = 0
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            if dx == 0 and dz == 0:
                continue
            w.chunks[(dx, dz)] = mc_world.Chunk(dx, dz)
    ch.blocks[5, 40, 5] = B.BY_NAME["stone"].id
    data = mc_mesher.build_chunk_data(w, ch)
    assert data is not None, "单方块应产生网格"
    verts, faces, uvs, cols, mats = data
    assert len(faces) == 6 and len(verts) == 24, (len(faces), len(verts))
    mesh = bpy.data.meshes.new("__test")
    mc_render._fill_mesh(mesh, verts, faces, uvs, cols, mats)
    got = sorted(tuple(round(c, 3) for c in p.normal) for p in mesh.polygons)
    want = sorted([(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, -1.0, 0.0),
                   (0.0, 1.0, 0.0), (0.0, 0.0, -1.0), (0.0, 0.0, 1.0)])
    assert got == want, f"法线不对：{got}"
    assert len(set(faces.ravel().tolist())) == 24
    assert 0.0 <= cols.min() and cols.max() <= 1.0
    bpy.data.meshes.remove(mesh)
    print("[OK] 单方块法线/绕序/顶点色单元测试通过")


unit_test_normals()


# --------------------------------------------------------------------------
# 2. 找取景点：草多、有树、最好靠海
# --------------------------------------------------------------------------
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
mc_render.clear_world_objects()
scene = bpy.context.scene

world = mc_world.World(seed=SEED)
# 先只生成高度列（用 cheap 方式：直接生成区块）
t0 = time.time()
for cx in range(-SEARCH, SEARCH + 1):
    for cz in range(-SEARCH, SEARCH + 1):
        world.get_chunk(cx, cz)
print(f"预生成 {(2*SEARCH+1)**2} 个区块耗时 {time.time()-t0:.2f}s")

grass_id = B.BY_NAME["grass_block"].id
log_id = B.BY_NAME["oak_log"].id
best, best_score = (0, 0), -1e9
for cx in range(-SEARCH + 1, SEARCH):
    for cz in range(-SEARCH + 1, SEARCH):
        ch = world.chunks[(cx, cz)]
        b = ch.blocks
        top = np.zeros((16, 16), dtype=np.int32) - 1
        nz = np.nonzero(b)
        for x, y, z in zip(*nz):
            top[x, z] = max(top[x, z], y)
        grass = int(np.count_nonzero(b[:, :, :] == grass_id))
        trees = int(np.count_nonzero(b == log_id))
        sea = int(np.count_nonzero(top < SEA_LEVEL))
        score = grass * 3 + trees * 8 + min(sea, 60) * 2 - abs(top.mean() - 70) * 2
        if score > best_score:
            best_score, best = score, (cx, cz)
print(f"最佳区块 {best} 分数 {best_score:.0f}")

cx0, cz0 = best
coords = [(cx0 + dx, cz0 + dz)
          for dx in range(-VIEW_R, VIEW_R + 1)
          for dz in range(-VIEW_R, VIEW_R + 1)]
for cx, cz in coords:
    world.get_chunk(cx, cz)

mats = mc_render.ensure_materials()
t0 = time.time()
total_faces = 0
for cx, cz in coords:
    ch = world.chunks[(cx, cz)]
    data = mc_mesher.build_chunk_data(world, ch)
    if data is not None:
        total_faces += len(data[1])
    mc_render.build_chunk_object(cx, cz, data, mats)
print(f"渲染区块 {len(coords)} 个  建网格 {time.time()-t0:.2f}s  总面数 {total_faces:,}")

bad = sum(1 for cx, cz in coords
          if (o := bpy.data.objects.get(f"MC_chunk_{cx}_{cz}")) is not None
          and len(o.data.polygons) and o.data.validate())
print(f"网格校验：{bad} 个区块有被修正的数据（0 最好）")

counts: dict[str, int] = {}
for cx, cz in coords:
    for bid, cnt in zip(*np.unique(world.chunks[(cx, cz)].blocks, return_counts=True)):
        counts[B.BLOCKS[int(bid)].name] = counts.get(B.BLOCKS[int(bid)].name, 0) + int(cnt)
print("方块统计:", ", ".join(f"{k}:{v}" for k, v in
                            sorted(counts.items(), key=lambda kv: -kv[1])[:10]))


# --------------------------------------------------------------------------
# 3. 相机 + 渲染
# --------------------------------------------------------------------------
from mathutils import Vector  # noqa: E402

cam = mc_render.ensure_camera()
mc_render.ensure_world_lighting()
sun = bpy.data.objects.get("MC_Sun")
if sun is not None:
    sun.data.energy = 1.7
    sun.rotation_euler = (math.radians(46), 0.0, math.radians(30))
if scene.world is not None:
    for n in scene.world.node_tree.nodes:
        if n.type == "BACKGROUND":
            n.inputs[1].default_value = 0.5

# 相机对准区块中心的地表
ccx, ccz = cx0 * 16 + 8, cz0 * 16 + 8
th = world.highest_solid(ccx, ccz)
if th < 0:
    th = 70
cam.location = (ccx - 20.0, ccz - 26.0, th + 17.0)
target = Vector((ccx + 3.0, ccz + 6.0, th - 1.0))
cam.rotation_euler = (target - Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
print(f"取景：({ccx},{ccz}) 高度 {th}")

scene.camera = cam
scene.render.engine = "CYCLES"
scene.cycles.samples = 96
scene.cycles.use_denoising = True
try:
    scene.cycles.device = "CPU"
except Exception:
    pass
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = OUT
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"

print("开始渲染 ...")
t0 = time.time()
bpy.ops.render.render(write_still=True)
print(f"渲染完成 {time.time()-t0:.1f}s -> {OUT}")

atlas_img = mc_render.ensure_atlas()
atlas_path = os.path.join(ROOT, "atlas_dump.png")
try:
    atlas_img.filepath_raw = atlas_path
    atlas_img.file_format = "PNG"
    atlas_img.save()
    print("图集已导出:", atlas_path)
except Exception as exc:      # pragma: no cover
    print("图集导出失败:", exc)

print("=" * 60)
