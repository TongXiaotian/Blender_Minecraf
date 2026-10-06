"""射线/视线方向一致性测试（不需要 GPU）。

用法：blender --background --factory-startup --python tools/test_aim.py
"""
from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_minecraft import mc_player  # noqa: E402
from blender_minecraft.mc_raycast import look_vector  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


def near(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


print("=" * 60)
# 1. 视线方向基本朝向（世界约定：y 是高度；yaw=0 朝 -Z）
check("yaw=0,pitch=0 朝 -Z", near(look_vector(0, 0), (0, 0, -1), 1e-9),
      str(look_vector(0, 0)))
check("yaw=90° 朝 -X", near(look_vector(math.pi / 2, 0), (-1, 0, 0), 1e-9),
      str(look_vector(math.pi / 2, 0)))
check("yaw=-90° 朝 +X", near(look_vector(-math.pi / 2, 0), (1, 0, 0), 1e-9),
      str(look_vector(-math.pi / 2, 0)))
check("yaw=180° 朝 +Z", near(look_vector(math.pi, 0), (0, 0, 1), 1e-9),
      str(look_vector(math.pi, 0)))
check("抬头 pitch=90° 朝上", near(look_vector(0, math.pi / 2), (0, 1, 0), 1e-9),
      str(look_vector(0, math.pi / 2)))
check("低头 pitch=-45° 水平/垂直分量相等",
      near(look_vector(0, -math.pi / 4), (0, -0.70710678, -0.70710678), 1e-6),
      str(look_vector(0, -math.pi / 4)))
check("方向是单位向量",
      abs(sum(c * c for c in look_vector(1.1, -0.7)) - 1.0) < 1e-9)

# 2. 和玩家移动方向一致（按 W 应该朝视线水平方向走）
print("2. 视线与移动方向一致性")
p = mc_player.Player(spawn=(0.0, 100.0, 0.0))

class FlatWorld:
    """只有 y<64 是实心的假世界。"""
    def is_loaded(self, x, z):
        return True

    def get_block(self, x, y, z):
        return 1 if y < 64 else 0


world = FlatWorld()
for yaw_deg in (0, 45, 90, 135, 180, 270):
    p.pos[:] = (0.5, 70.0, 0.5)
    p.vel[:] = 0
    p.yaw = math.radians(yaw_deg)
    p.pitch = 0.0
    p.on_ground = True
    lv = look_vector(p.yaw, 0.0)
    flat = (lv[0], lv[2])
    n = math.hypot(*flat)
    flat = (flat[0] / n, flat[1] / n)
    for _ in range(120):
        p.update(world, 1 / 60.0, {"forward"})
    move = (p.pos[0] - 0.5, p.pos[2] - 0.5)
    m = math.hypot(*move)
    if m < 1e-6:
        check(f"yaw={yaw_deg}° 前进方向", False, "没有移动")
        continue
    move = (move[0] / m, move[1] / m)
    dot = flat[0] * move[0] + flat[1] * move[1]
    check(f"yaw={yaw_deg}° 前进方向与视线水平方向一致", dot > 0.99,
          f"dot={dot:.3f} 视线={tuple(round(v,3) for v in flat)} "
          f"实际={tuple(round(float(v),3) for v in move)}")

# 3. 按 D 应该往视线的右手边走
print("3. 左右平移方向")
for yaw_deg in (0, 90, 180):
    p.pos[:] = (0.5, 70.0, 0.5)
    p.vel[:] = 0
    p.yaw = math.radians(yaw_deg)
    p.on_ground = True
    for _ in range(120):
        p.update(world, 1 / 60.0, {"right"})
    right = (math.cos(p.yaw), -math.sin(p.yaw))
    move = (p.pos[0] - 0.5, p.pos[2] - 0.5)
    m = math.hypot(*move)
    if m < 1e-6:
        check(f"yaw={yaw_deg}° 右移方向", False, "没有移动")
        continue
    move = (move[0] / m, move[1] / m)
    dot = right[0] * move[0] + right[1] * move[1]
    check(f"yaw={yaw_deg}° 按 D 往右走", dot > 0.99,
          f"dot={dot:.3f} 期望={tuple(round(v,3) for v in right)} "
          f"实际={tuple(round(float(v),3) for v in move)}")

print("=" * 60)
print("全部通过 ✅" if not FAIL else f"失败 {len(FAIL)} 项：" + ", ".join(FAIL))
print("=" * 60)
