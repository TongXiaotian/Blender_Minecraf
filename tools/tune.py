"""调参脚本：为高度/生物群系公式挑频率和阈值（世界种子折叠后与 mc_world 一致）。"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_minecraft import mc_world  # noqa: E402
from blender_minecraft.mc_const import SEA_LEVEL, WORLD_H  # noqa: E402

SEED = 20240501
FOLDED = SEED & 0xFFFF
print("折叠后的种子:", FOLDED)

N = 1024
ax = np.arange(N, dtype=np.float64)
gx, gz = np.meshgrid(ax, ax, indexing="ij")


def stats(name, v):
    print(f"{name:10s} mean={v.mean():.3f} std={v.std():.3f} "
          f"p10={np.percentile(v,10):.3f} p50={np.percentile(v,50):.3f} "
          f"p90={np.percentile(v,90):.3f}")


cont = mc_world.fbm2(gx, gz, FOLDED + 11, 1.0 / 220.0, octaves=4)
mount = mc_world.fbm2(gx, gz, FOLDED + 23, 1.0 / 90.0, octaves=4)
rough = mc_world.noise2(gx, gz, FOLDED + 37, 1.0 / 26.0)
detail = mc_world.noise2(gx, gz, FOLDED + 53, 1.0 / 11.0)
for f in (1 / 200.0, 1 / 160.0, 1 / 120.0):
    stats(f"temp 1/{int(1/f)}", mc_world.fbm2(gx, gz, FOLDED + 71, f, octaves=3))
for f in (1 / 160.0, 1 / 120.0, 1 / 90.0):
    stats(f"moist 1/{int(1/f)}", mc_world.fbm2(gx, gz, FOLDED + 89, f, octaves=3))

temp = mc_world.fbm2(gx, gz, FOLDED + 71, 1.0 / 160.0, octaves=3)
moist = mc_world.fbm2(gx, gz, FOLDED + 89, 1.0 / 120.0, octaves=3)

c = (cont - 0.5) * 2.0
m = np.clip((mount - 0.58) / 0.42, 0.0, 1.0) ** 1.6
h = np.clip(66.0 + c * 20.0 + m * 58.0 + rough * 2.5 + detail * 1.5, 4, WORLD_H - 14)
print(f"\nheight mean={h.mean():.1f} p10={np.percentile(h,10):.1f} "
      f"p50={np.percentile(h,50):.1f} p90={np.percentile(h,90):.1f} max={h.max():.1f}")
print(f"海洋比例(高度<{SEA_LEVEL}): {(h < SEA_LEVEL).mean()*100:.1f}%")
print(f"高山比例(高度>{SEA_LEVEL+34}): {(h > SEA_LEVEL+34).mean()*100:.1f}%")

for thr in (0.32, 0.34, 0.36):
    print(f"snowy 阈值 {thr}: {(temp < thr).mean()*100:.1f}%")
for tthr, mthr in ((0.62, 0.45), (0.58, 0.5), (0.60, 0.42)):
    print(f"desert temp>{tthr} & moist<{mthr}: "
          f"{((temp > tthr) & (moist < mthr)).mean()*100:.1f}%")
print(f"沙滩条件(高度 <= {SEA_LEVEL+1}): {(h <= SEA_LEVEL + 1).mean()*100:.1f}%")
