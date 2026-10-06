"""把区块体素数据转成三角网格（纯 numpy，向量化，很快）。

关键点：
* 只输出"看得见"的面（被不透明方块挡住的面直接剔除）；
* 每个顶点烘焙 环境光遮蔽(AO) × 面朝向明暗，写进顶点色，
  这样不需要光照贴图也能得到《我的世界》那种立体感；
* 透明的方块（水/玻璃/冰）输出到第二个材质槽。
"""
from __future__ import annotations

import numpy as np

from . import mc_blocks as B
from .mc_const import (FACE_NX, FACE_NY, FACE_NZ, FACE_PX, FACE_PY, FACE_PZ,
                       FACE_SHADE, CHUNK_X, CHUNK_Z, WORLD_H)
from .mc_textures import TILE_NAMES, tile_uv

# 提前把每张贴图的 UV 范围算成数组，网格生成时一次性查表（避免逐面 Python 循环）
_TILE_UV = np.array([tile_uv(i) for i in range(len(TILE_NAMES))], dtype=np.float32)

# 每个面的 4 个角在"方块空间"里的偏移 (x, y=高度, z)
# 顺序保证从面外侧看是逆时针（Blender 用右手定则算法线）
_FACE_CORNERS = {
    FACE_PX: ((1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)),
    FACE_NX: ((0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)),
    FACE_PY: ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)),
    FACE_NY: ((0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)),
    FACE_PZ: ((1, 0, 1), (0, 0, 1), (0, 1, 1), (1, 1, 1)),
    FACE_NZ: ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)),
}

# 贴图 4 个角对应的 (u, v)，v 向上
_CORNER_UV = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))

# 归一化的面法线（数组索引空间 (x, y=高度, z)）
_FACE_NORMAL = {
    FACE_PX: (1, 0, 0),
    FACE_NX: (-1, 0, 0),
    FACE_PY: (0, 1, 0),
    FACE_NY: (0, -1, 0),
    FACE_PZ: (0, 0, 1),
    FACE_NZ: (0, 0, -1),
}

# 面内两个切向轴，顺序保证 cross(t1, t2) == 法线
_FACE_TANGENTS = {
    FACE_PX: ((0, 0, 1), (0, 1, 0)),
    FACE_NX: ((0, 1, 0), (0, 0, 1)),
    FACE_PY: ((1, 0, 0), (0, 0, 1)),
    FACE_NY: ((0, 0, 1), (1, 0, 0)),
    FACE_PZ: ((-1, 0, 0), (0, 1, 0)),
    FACE_NZ: ((1, 0, 0), (0, 1, 0)),
}

# 4 个角在 (t1, t2) 上的符号
_AO_SIGNS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
_AO_FACTOR = np.array([0.55, 0.72, 0.86, 1.0], dtype=np.float32)

# 透明方块（走材质槽 1）
_TRANSPARENT = np.array([(not b.opaque) and b.solid or b.liquid for b in B.BLOCKS], dtype=bool)


def _pad_volume(world, chunk):
    """把区块 + 3x3 邻居拼成带 1 格外扩边的体素数组，方便统一计算面剔除和 AO。"""
    size = CHUNK_X * 3 + 2          # 50
    vol = np.zeros((size, WORLD_H + 2, size), dtype=np.uint8)
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            nb = world.get_chunk(chunk.cx + dx, chunk.cz + dz, create=True)
            ox = 16 + dx * CHUNK_X
            oz = 16 + dz * CHUNK_Z
            vol[ox:ox + CHUNK_X, 1:WORLD_H + 1, oz:oz + CHUNK_Z] = nb.blocks
    return vol


def _face_arrays(vol, face):
    """返回某个朝向上所有可见面的信息（只处理中间那个区块）。"""
    nx, ny, nz = _FACE_NORMAL[face]
    x0, x1 = CHUNK_X, CHUNK_X * 2          # 中间区块在 padded 体素里的范围
    z0, z1 = CHUNK_Z, CHUNK_Z * 2
    block = vol[x0:x1, 1:-1, z0:z1]
    nid = vol[x0 + nx:x1 + nx, 1 + ny:WORLD_H + 1 + ny, z0 + nz:z1 + nz]

    opaque_n = B.OPAQUE_TABLE[nid]
    same_soft = (nid == block) & ~B.OPAQUE_TABLE[block]
    visible = (block != 0) & ~opaque_n & ~same_soft
    xs, ys, zs = np.nonzero(visible)
    if len(xs) == 0:
        return None

    ids = block[xs, ys, zs]
    n = len(xs)

    # ---- 环境光遮蔽 ----
    px, py, pz = xs + x0, ys + 1, zs + z0
    t1, t2 = _FACE_TANGENTS[face]
    shade = np.empty((4, n), dtype=np.float32)
    for j, (p, q) in enumerate(_AO_SIGNS):
        def idx(t, s):
            return (px + nx + s * t[0], py + ny + s * t[1], pz + nz + s * t[2])
        s1 = B.OPAQUE_TABLE[vol[idx(t1, p)]]
        s2 = B.OPAQUE_TABLE[vol[idx(t2, q)]]
        cor = B.OPAQUE_TABLE[vol[(px + nx + p * t1[0] + q * t2[0],
                                  py + ny + p * t1[1] + q * t2[1],
                                  pz + nz + p * t1[2] + q * t2[2])]]
        lvl = np.where(s1 & s2, 0, 3 - (s1.astype(np.int8) + s2.astype(np.int8)
                                        + cor.astype(np.int8)))
        shade[j] = _AO_FACTOR[lvl]

    # ---- 顶点 / UV / 顶点色 ----
    verts = np.empty((n * 4, 3), dtype=np.float32)
    uvs = np.empty((n * 4, 2), dtype=np.float32)
    cols = np.empty((n * 4, 4), dtype=np.float32)
    tiles = B.TILE_TABLE[ids, face]
    uv4 = _TILE_UV[tiles]                     # (n, 4) = u0, v0, u1, v1
    u0, v0, u1, v1 = uv4[:, 0], uv4[:, 1], uv4[:, 2], uv4[:, 3]
    base_shade = FACE_SHADE[face]
    for j, (ox, oy, oz) in enumerate(_FACE_CORNERS[face]):
        verts[j::4, 0] = xs + ox
        verts[j::4, 1] = zs + oz          # Blender Y = 方块 z
        verts[j::4, 2] = ys + oy          # Blender Z = 方块 y（高度）
        cu, cv = _CORNER_UV[j]
        uvs[j::4, 0] = u0 + (u1 - u0) * cu
        uvs[j::4, 1] = v0 + (v1 - v0) * cv
        cols[j::4, 0] = base_shade * shade[j]
        cols[j::4, 1] = base_shade * shade[j]
        cols[j::4, 2] = base_shade * shade[j]
        cols[j::4, 3] = 1.0

    mat = np.where(_TRANSPARENT[ids], 1, 0).astype(np.int32)
    return verts, uvs, cols, mat


def build_chunk_data(world, chunk):
    """生成区块的网格数据。返回 None 表示空区块。"""
    vol = _pad_volume(world, chunk)
    v_list, uv_list, c_list, m_list = [], [], [], []
    for face in (FACE_PX, FACE_NX, FACE_PY, FACE_NY, FACE_PZ, FACE_NZ):
        out = _face_arrays(vol, face)
        if out is None:
            continue
        v_list.append(out[0]); uv_list.append(out[1])
        c_list.append(out[2]); m_list.append(out[3])
    if not v_list:
        return None
    verts = np.concatenate(v_list, axis=0)
    uvs = np.concatenate(uv_list, axis=0)
    cols = np.concatenate(c_list, axis=0)
    mats = np.concatenate(m_list, axis=0)
    faces = np.arange(len(verts), dtype=np.int32).reshape(-1, 4)
    return verts, faces, uvs, cols, mats
