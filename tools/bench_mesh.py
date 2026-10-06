"""网格生成 / 世界生成 性能基准。

用法：blender --background --factory-startup --python tools/bench_mesh.py -- [区块数] [种子]
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_minecraft import mc_mesher, mc_world  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
N = int(argv[0]) if argv else 81
SEED = int(argv[1]) if len(argv) > 1 else 20240501

world = mc_world.World(seed=SEED)
coords = []
r = 0
while len(coords) < N:
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            if max(abs(dx), abs(dz)) == r:
                coords.append((dx, dz))
    r += 1
coords = coords[:N]

t0 = time.perf_counter()
for cx, cz in coords:
    world.get_chunk(cx, cz)
t_gen = time.perf_counter() - t0

t0 = time.perf_counter()
faces = 0
times = []
for cx, cz in coords:
    t1 = time.perf_counter()
    data = mc_mesher.build_chunk_data(world, world.chunks[(cx, cz)])
    times.append(time.perf_counter() - t1)
    if data is not None:
        faces += len(data[1])
t_mesh = time.perf_counter() - t0

print(f"区块数 {N}")
print(f"地形生成 {t_gen:.3f}s  平均 {t_gen/N*1000:.1f} ms/区块")
print(f"网格生成 {t_mesh:.3f}s  平均 {t_mesh/N*1000:.1f} ms/区块  "
      f"中位 {np.median(times)*1000:.1f} ms  最慢 {max(times)*1000:.1f} ms")
print(f"总面数 {faces:,}  平均 {faces/N:.0f} 面/区块")
print(f"如果按 60fps 每帧生成 1 个区块：需要 {t_mesh/N*1000:.1f} ms/帧 "
      f"→ 最高约 {1000/(t_mesh/N*1000):.0f} 区块/秒")
