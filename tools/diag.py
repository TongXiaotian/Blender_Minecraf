"""诊断脚本：噪声分布、生物群系比例、网格 validate 行为。"""
from __future__ import annotations

import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_minecraft import mc_blocks as B          # noqa: E402
from blender_minecraft import mc_mesher, mc_render, mc_world  # noqa: E402
from blender_minecraft.mc_const import SEA_LEVEL, WORLD_H  # noqa: E402

seed = 20240501
N = 256
xs = np.arange(N, dtype=np.float64)
gx, gz = np.meshgrid(xs, xs, indexing="ij")

for name, args in [
    ("cont", (seed + 11, 1.0 / 220.0, 4)),
    ("mount", (seed + 23, 1.0 / 90.0, 4)),
    ("rough", (seed + 37, 1.0 / 26.0, 1)),
    ("temp", (seed + 71, 1.0 / 420.0, 3)),
    ("moist", (seed + 89, 1.0 / 300.0, 3)),
]:
    s, freq, oct_ = args
    v = mc_world.fbm2(gx, gz, s, freq, octaves=oct_)
    print(f"{name:6s} mean={v.mean():.3f} std={v.std():.3f} "
          f"p5={np.percentile(v,5):.3f} p50={np.percentile(v,50):.3f} "
          f"p95={np.percentile(v,95):.3f} min={v.min():.3f} max={v.max():.3f}")

# ---- 新高度公式的统计 ----
cont = mc_world.fbm2(gx, gz, seed + 11, 1.0 / 220.0, octaves=4)
mount = mc_world.fbm2(gx, gz, seed + 23, 1.0 / 90.0, octaves=4)
rough = mc_world.noise2(gx, gz, seed + 37, 1.0 / 26.0)
detail = mc_world.noise2(gx, gz, seed + 53, 1.0 / 11.0)
temp = mc_world.fbm2(gx, gz, seed + 71, 1.0 / 420.0, octaves=3)
moist = mc_world.fbm2(gx, gz, seed + 89, 1.0 / 300.0, octaves=3)

c = (cont - 0.5) * 2.0
m = np.clip((mount - 0.58) / 0.42, 0.0, 1.0) ** 1.6
h = np.clip(66.0 + c * 20.0 + m * 58.0 + rough * 2.5 + detail * 1.5, 4, WORLD_H - 14)
print(f"\nheight mean={h.mean():.1f} p5={np.percentile(h,5):.1f} "
      f"p50={np.percentile(h,50):.1f} p95={np.percentile(h,95):.1f} "
      f"max={h.max():.1f}")
print(f"低于海平面({SEA_LEVEL})的比例: {(h < SEA_LEVEL).mean()*100:.1f}%")
print(f"snowy(temp<p33={np.percentile(temp,33):.3f}): {(temp < np.percentile(temp,33)).mean()*100:.1f}%")
print(f"desert(temp>p67 & moist<p50): {((temp > np.percentile(temp,67)) & (moist < 0.5)).mean()*100:.1f}%")

# ---- 整片地形解剖 + validate 行为 ----
w = mc_world.World(seed=seed)
coords = [(cx, cz) for cx in range(-2, 3) for cz in range(-2, 3)]
for cx, cz in coords:
    w.get_chunk(cx, cz)

counts: dict[str, int] = {}
cave_air = 0
for cx, cz in coords:
    ch = w.chunks[(cx, cz)]
    for bid, cnt in zip(*np.unique(ch.blocks, return_counts=True)):
        counts[B.BLOCKS[int(bid)].name] = counts.get(B.BLOCKS[int(bid)].name, 0) + int(cnt)
    # 地表以下的空气 = 洞穴
    for lx in range(16):
        for lz in range(16):
            col = ch.blocks[lx, :, lz]
            nz = np.nonzero(col)[0]
            if len(nz) > 6:
                top = nz[-1]
                cave_air += int(np.count_nonzero(col[1:top] == 0))
print("\n方块统计:", ", ".join(f"{k}:{v}" for k, v in
                            sorted(counts.items(), key=lambda kv: -kv[1])[:12]))
print("洞穴空气方块数:", cave_air)

# validate 行为
mats = mc_render.ensure_materials()
ch = w.chunks[(0, 0)]
data = mc_mesher.build_chunk_data(w, ch)
mesh = bpy.data.meshes.new("diag")
mc_render._fill_mesh(mesh, *data)
before = (len(mesh.vertices), len(mesh.polygons), len(mesh.loops), len(mesh.edges))
changed = mesh.validate()
after = (len(mesh.vertices), len(mesh.polygons), len(mesh.loops), len(mesh.edges))
print(f"\nvalidate: changed={changed}  before(v,e,p,l)={before}  after={after}")
if changed:
    # 找出被改了什么
    bad_loops = sum(1 for l in mesh.loops if l.vertex_index >= len(mesh.vertices))
    print("越界 loop 数:", bad_loops)
    print("polygon 顶点数分布:", {n: sum(1 for p in mesh.polygons if p.loop_total == n)
                                 for n in set(p.loop_total for p in mesh.polygons)})
