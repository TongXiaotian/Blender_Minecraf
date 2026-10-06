"""体素射线检测（Amanatides & Woo 的 DDA 算法）。

用来决定玩家视线指着哪个方块、以及放置方块的位置。
"""
from __future__ import annotations

import math

import numpy as np

from . import mc_blocks as B


def raycast(world, origin, direction, max_dist: float = 5.0, hit_liquid: bool = False):
    """从 origin 沿 direction 投射。

    返回 (命中方块坐标, 面法线(整数三元组), 方块 id)；
    没打到任何东西返回 None。法线指向"玩家所在的一侧"，用它算放置位置。
    """
    ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
    dx, dy, dz = float(direction[0]), float(direction[1]), float(direction[2])
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if norm < 1e-9:
        return None
    dx, dy, dz = dx / norm, dy / norm, dz / norm

    x, y, z = math.floor(ox), math.floor(oy), math.floor(oz)

    step_x = 1 if dx > 0 else (-1 if dx < 0 else 0)
    step_y = 1 if dy > 0 else (-1 if dy < 0 else 0)
    step_z = 1 if dz > 0 else (-1 if dz < 0 else 0)

    inf = float("inf")
    t_delta_x = abs(1.0 / dx) if dx != 0 else inf
    t_delta_y = abs(1.0 / dy) if dy != 0 else inf
    t_delta_z = abs(1.0 / dz) if dz != 0 else inf

    def first_t(o, i, d, s):
        if d == 0:
            return inf
        boundary = i + (1 if s > 0 else 0)
        return abs(boundary - o) / abs(d)

    t_max_x = first_t(ox, x, dx, step_x)
    t_max_y = first_t(oy, y, dy, step_y)
    t_max_z = first_t(oz, z, dz, step_z)

    normal = (0, 0, 0)
    t = 0.0
    for _ in range(512):
        if t > max_dist:
            return None
        bid = world.get_block(x, y, z)
        if bid:
            if hit_liquid or not B.LIQUID_TABLE[bid]:
                return (x, y, z), normal, int(bid)
        if t_max_x < t_max_y:
            if t_max_x < t_max_z:
                x += step_x
                t = t_max_x
                t_max_x += t_delta_x
                normal = (-step_x, 0, 0)
            else:
                z += step_z
                t = t_max_z
                t_max_z += t_delta_z
                normal = (0, 0, -step_z)
        else:
            if t_max_y < t_max_z:
                y += step_y
                t = t_max_y
                t_max_y += t_delta_y
                normal = (0, -step_y, 0)
            else:
                z += step_z
                t = t_max_z
                t_max_z += t_delta_z
                normal = (0, 0, -step_z)
    return None


def look_vector(yaw: float, pitch: float):
    """由 yaw/pitch（弧度）算视线方向。

    坐标约定与 Minecraft 一致：(x, y, z)，其中 y 是高度。
    yaw=0 时朝 -Z 水平看，pitch>0 抬头。
    水平分量必须和移动用的 (-sin yaw, -cos yaw) 完全一致，否则准星指着的方块
    和射线打到的方块会对不上。
    """
    cp = math.cos(pitch)
    return (-math.sin(yaw) * cp, math.sin(pitch), -math.cos(yaw) * cp)


def view_matrix_axes(yaw: float, pitch: float):
    """相机的前 / 右 / 上向量（同样是 y 向上的世界约定）。"""
    forward = np.array(look_vector(yaw, pitch), dtype=np.float64)
    world_up = np.array((0.0, 1.0, 0.0))
    right = np.cross(forward, world_up)
    n = np.linalg.norm(right)
    if n < 1e-6:
        right = np.array((1.0, 0.0, 0.0))
    else:
        right /= n
    up = np.cross(right, forward)
    return forward, right, up


# 世界约定 (x, y=高度, z) -> Blender 世界坐标 (X, Y, Z=向上)
def to_blender(v):
    return (float(v[0]), float(v[2]), float(v[1]))
