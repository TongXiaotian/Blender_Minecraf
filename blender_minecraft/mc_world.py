"""体素世界：分块存储 + 程序化地形生成（噪声、生物群系、洞穴、矿脉、树木）。

地形用整数哈希噪声生成，因此区块可以按需、无序地生成而结果始终一致。
"""
from __future__ import annotations

import numpy as np

from . import mc_blocks as B
from .mc_const import BEDROCK_LEVEL, CHUNK_X, CHUNK_Z, SEA_LEVEL, WORLD_H

_U64 = np.uint64


# --------------------------------------------------------------------------
# 噪声
# --------------------------------------------------------------------------
def _hash2(ix, iz, seed):
    """整数哈希 -> [0,1) 的 2D 值噪声格点。"""
    h = (ix.astype(np.int64).astype(_U64) * _U64(0x9E3779B97F4A7C15)
         ^ iz.astype(np.int64).astype(_U64) * _U64(0xC2B2AE3D27D4EB4F)
         ^ _U64(seed & 0xFFFFFFFFFFFF))
    h ^= h >> _U64(29)
    h *= _U64(0xBF58476D1CE4E5B9)
    h ^= h >> _U64(32)
    h *= _U64(0x94D049BB133111EB)
    h ^= h >> _U64(31)
    return (h >> _U64(11)).astype(np.float64) * (1.0 / 9007199254740992.0)


def _hash3(ix, iy, iz, seed):
    h = (ix.astype(np.int64).astype(_U64) * _U64(0x9E3779B97F4A7C15)
         ^ iy.astype(np.int64).astype(_U64) * _U64(0xD6E8FEB86659FD93)
         ^ iz.astype(np.int64).astype(_U64) * _U64(0xC2B2AE3D27D4EB4F)
         ^ _U64(seed & 0xFFFFFFFFFFFF))
    h ^= h >> _U64(30)
    h *= _U64(0xBF58476D1CE4E5B9)
    h ^= h >> _U64(27)
    h *= _U64(0x94D049BB133111EB)
    h ^= h >> _U64(31)
    return (h >> _U64(11)).astype(np.float64) * (1.0 / 9007199254740992.0)


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def noise2(x, z, seed, freq):
    """双线性平滑插值的 2D 值噪声，返回 [0,1)。"""
    x = np.asarray(x, dtype=np.float64) * freq
    z = np.asarray(z, dtype=np.float64) * freq
    x0 = np.floor(x)
    z0 = np.floor(z)
    tx = _smooth(x - x0)
    tz = _smooth(z - z0)
    x0 = x0.astype(np.int64)
    z0 = z0.astype(np.int64)
    c00 = _hash2(x0, z0, seed)
    c10 = _hash2(x0 + 1, z0, seed)
    c01 = _hash2(x0, z0 + 1, seed)
    c11 = _hash2(x0 + 1, z0 + 1, seed)
    a = c00 * (1 - tx) + c10 * tx
    b = c01 * (1 - tx) + c11 * tx
    return a * (1 - tz) + b * tz


def noise3(x, y, z, seed, freq):
    """三线性插值的 3D 值噪声（用于洞穴）。"""
    x = np.asarray(x, dtype=np.float64) * freq
    y = np.asarray(y, dtype=np.float64) * freq
    z = np.asarray(z, dtype=np.float64) * freq
    x0, y0, z0 = np.floor(x), np.floor(y), np.floor(z)
    tx, ty, tz = _smooth(x - x0), _smooth(y - y0), _smooth(z - z0)
    x0, y0, z0 = x0.astype(np.int64), y0.astype(np.int64), z0.astype(np.int64)
    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = ((tx if dx else 1 - tx) * (ty if dy else 1 - ty)
                     * (tz if dz else 1 - tz))
                out = out + w * _hash3(x0 + dx, y0 + dy, z0 + dz, seed)
    return out


def fbm2(x, z, seed, base_freq, octaves=4, lacunarity=2.0, gain=0.5):
    total = np.zeros(np.broadcast(x, z).shape, dtype=np.float64)
    amp, freq, norm = 1.0, base_freq, 0.0
    for i in range(octaves):
        total += amp * noise2(x, z, seed + i * 7919, freq)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


# --------------------------------------------------------------------------
# 区块
# --------------------------------------------------------------------------
class Chunk:
    """一列 16x16xWORLD_H 的方块。"""

    __slots__ = ("cx", "cz", "blocks", "dirty", "solid_obj", "trans_obj",
                 "mesh_version", "populated")

    def __init__(self, cx, cz):
        self.cx = cx
        self.cz = cz
        self.blocks = np.zeros((CHUNK_X, WORLD_H, CHUNK_Z), dtype=np.uint8)
        self.dirty = True
        self.populated = False
        self.solid_obj = None
        self.trans_obj = None
        self.mesh_version = 0

    @property
    def origin(self):
        return self.cx * CHUNK_X, self.cz * CHUNK_Z


# --------------------------------------------------------------------------
# 世界
# --------------------------------------------------------------------------
class World:
    def __init__(self, seed: int = 20240501):
        self.seed = int(seed)
        self.chunks: dict[tuple[int, int], Chunk] = {}
        self.ores = (
            ("coal_ore", 1, 1.0),
            ("coal_ore", 2, 0.7),
            ("iron_ore", 1, 0.85),
            ("gold_ore", 2, 0.55),
            ("diamond_ore", 3, 0.4),
        )

    # ---------- 区块访问 ----------
    def get_chunk(self, cx, cz, create=True) -> Chunk | None:
        key = (cx, cz)
        ch = self.chunks.get(key)
        if ch is None and create:
            ch = Chunk(cx, cz)
            self.chunks[key] = ch
            self.generate(ch)
        return ch

    def has_chunk(self, cx, cz) -> bool:
        return (cx, cz) in self.chunks

    def is_loaded(self, wx, wz) -> bool:
        cx = int(np.floor(wx)) // CHUNK_X
        cz = int(np.floor(wz)) // CHUNK_Z
        return (cx, cz) in self.chunks

    # ---------- 方块访问 ----------
    def get_block(self, wx, wy, wz) -> int:
        wy = int(wy)
        if wy < BEDROCK_LEVEL:
            return B.BY_NAME["bedrock"].id
        if wy >= WORLD_H:
            return 0
        cx, lx = divmod(int(np.floor(wx)), CHUNK_X)
        cz, lz = divmod(int(np.floor(wz)), CHUNK_Z)
        ch = self.chunks.get((cx, cz))
        if ch is None:
            return 0
        return int(ch.blocks[lx, wy, lz])

    def set_block(self, wx, wy, wz, block_id: int, mark=True):
        wy = int(wy)
        if wy < BEDROCK_LEVEL or wy >= WORLD_H:
            return
        cx, lx = divmod(int(np.floor(wx)), CHUNK_X)
        cz, lz = divmod(int(np.floor(wz)), CHUNK_Z)
        ch = self.get_chunk(cx, cz)
        if ch is None:
            return
        if ch.blocks[lx, wy, lz] == block_id:
            return
        ch.blocks[lx, wy, lz] = block_id
        if mark:
            self.mark_dirty(cx, cz)
            # 边界方块会影响相邻区块的面剔除 / AO
            if lx == 0:
                self.mark_dirty(cx - 1, cz)
            elif lx == CHUNK_X - 1:
                self.mark_dirty(cx + 1, cz)
            if lz == 0:
                self.mark_dirty(cx, cz - 1)
            elif lz == CHUNK_Z - 1:
                self.mark_dirty(cx, cz + 1)
            if lx in (0, CHUNK_X - 1) and lz in (0, CHUNK_Z - 1):
                self.mark_dirty(cx + (1 if lx == CHUNK_X - 1 else -1),
                                cz + (1 if lz == CHUNK_Z - 1 else -1))

    def mark_dirty(self, cx, cz):
        ch = self.chunks.get((cx, cz))
        if ch is not None:
            ch.dirty = True

    def is_solid(self, wx, wy, wz) -> bool:
        return bool(B.SOLID_TABLE[self.get_block(wx, wy, wz)])

    def is_liquid(self, wx, wy, wz) -> bool:
        return bool(B.LIQUID_TABLE[self.get_block(wx, wy, wz)])

    def highest_solid(self, wx, wz, below=WORLD_H) -> int:
        """返回该列最高的非空气方块的 y（含液体），找不到返回 -1。"""
        ch = self.chunks.get((int(np.floor(wx)) // CHUNK_X, int(np.floor(wz)) // CHUNK_Z))
        if ch is None:
            return -1
        lx = int(np.floor(wx)) % CHUNK_X
        lz = int(np.floor(wz)) % CHUNK_Z
        col = ch.blocks[lx, :min(below, WORLD_H), lz]
        nz = np.nonzero(col)[0]
        return int(nz[-1]) if len(nz) else -1

    # ---------- 地形生成 ----------
    def generate(self, chunk: Chunk):
        rng = np.random.default_rng(
            (self.seed * 1000003 + chunk.cx * 73856093 + chunk.cz * 19349663) & 0x7FFFFFFF)
        wx = chunk.cx * CHUNK_X + np.arange(CHUNK_X, dtype=np.float64)
        wz = chunk.cz * CHUNK_Z + np.arange(CHUNK_Z, dtype=np.float64)
        gx, gz = np.meshgrid(wx, wz, indexing="ij")   # (16,16)

        seed = self.seed & 0xFFFF
        # 大陆起伏 + 山脉
        cont = fbm2(gx, gz, seed + 11, 1.0 / 220.0, octaves=4)
        mount = fbm2(gx, gz, seed + 23, 1.0 / 90.0, octaves=4)
        rough = noise2(gx, gz, seed + 37, 1.0 / 26.0)
        detail = noise2(gx, gz, seed + 53, 1.0 / 11.0)

        c = (cont - 0.5) * 2.0
        m = np.clip((mount - 0.58) / 0.42, 0.0, 1.0) ** 1.6
        height = 66.0 + c * 21.0 + m * 58.0 + rough * 2.5 + detail * 1.5
        height = np.clip(height, 4, WORLD_H - 16).astype(np.int32)

        # 生物群系（频率取 120~160 格，这样一块区域内能看到几种群系）
        temp = fbm2(gx, gz, seed + 71, 1.0 / 160.0, octaves=3)
        moist = fbm2(gx, gz, seed + 89, 1.0 / 120.0, octaves=3)
        snowy = temp < 0.34
        desert = (temp > 0.57) & (moist < 0.52)
        # 高山：裸露岩石 / 雪顶
        rocky = height > 88
        snowcap = height > 96

        blk = chunk.blocks
        ys = np.arange(WORLD_H)
        ygrid = ys[None, :, None]                      # (1,H,1)
        hcol = height[:, None, :]                      # (X,1,Z)

        stone = B.BY_NAME["stone"].id
        dirt = B.BY_NAME["dirt"].id
        grass = B.BY_NAME["grass_block"].id
        sand = B.BY_NAME["sand"].id
        snow = B.BY_NAME["snow_block"].id
        bed = B.BY_NAME["bedrock"].id
        water = B.BY_NAME["water"].id

        solid_rock = ygrid <= (hcol - 4)
        blk[solid_rock] = stone
        soil = (ygrid <= hcol) & (ygrid > (hcol - 4))
        blk[soil] = dirt

        # 表层
        surface = (ygrid == hcol)
        # 靠海/低海拔 -> 沙滩
        beach = (height[:, None, :] <= SEA_LEVEL + 1)
        top_grass = surface & ~desert[:, None, :] & ~snowy[:, None, :] & ~beach
        top_grass &= ~rocky[:, None, :]
        top_sand = surface & (desert[:, None, :] | beach)
        top_snow = surface & ((snowy[:, None, :] & ~rocky[:, None, :])
                              | snowcap[:, None, :])
        top_stone = surface & rocky[:, None, :] & ~snowcap[:, None, :]
        blk[np.broadcast_to(top_grass, blk.shape)] = grass
        blk[np.broadcast_to(top_sand, blk.shape)] = sand
        blk[np.broadcast_to(top_snow, blk.shape)] = snow
        blk[np.broadcast_to(top_stone, blk.shape)] = stone
        # 沙漠表层下面是沙
        dsub = (ygrid < hcol) & (ygrid > hcol - 4) & desert[:, None, :]
        blk[np.broadcast_to(dsub, blk.shape)] = sand

        # 水
        water_mask = (ygrid > hcol) & (ygrid <= SEA_LEVEL)
        blk[np.broadcast_to(water_mask, blk.shape)] = water
        # 寒冷群系水面结冰
        ice = B.BY_NAME["ice"].id
        frozen = (ygrid == SEA_LEVEL) & water_mask & snowy[:, None, :]
        blk[np.broadcast_to(frozen, blk.shape)] = ice

        # 基岩
        blk[:, BEDROCK_LEVEL, :] = bed

        # 洞穴
        self._carve_caves(chunk, height)

        # 矿脉
        self._place_ores(chunk, rng)

        # 树木 / 植被
        self._place_trees(chunk, height, snowy, desert, rocky, moist, rng)

        chunk.dirty = True
        chunk.populated = True
        return chunk

    # ---------- 生成辅助 ----------
    def _carve_caves(self, chunk: Chunk, height):
        blk = chunk.blocks
        wx = chunk.cx * CHUNK_X + np.arange(CHUNK_X, dtype=np.float64)
        wz = chunk.cz * CHUNK_Z + np.arange(CHUNK_Z, dtype=np.float64)
        seed = self.seed & 0xFFFF
        for y0 in range(4, WORLD_H, 16):
            ys = np.arange(y0, min(y0 + 16, WORLD_H), dtype=np.float64)
            if len(ys) == 0:
                continue
            gx = wx[:, None, None]
            gy = ys[None, :, None]
            gz = wz[None, None, :]
            n1 = noise3(gx, gy * 2.2, gz, seed + 131, 1.0 / 30.0)
            n2 = noise3(gx + 100, gy * 2.2, gz - 100, seed + 137, 1.0 / 30.0)
            cave = (np.abs(n1 - 0.5) < 0.055) & (np.abs(n2 - 0.5) < 0.055)
            hh = height[:, None, :]
            yy = ys[None, :, None]
            cave &= (yy < hh - 2) & (yy > 2)
            sl = slice(y0, min(y0 + 16, WORLD_H))
            region = blk[:, sl, :]
            region[cave] = 0
        return chunk

    def _place_ores(self, chunk: Chunk, rng):
        blk = chunk.blocks
        stone = B.BY_NAME["stone"].id
        for name, tries, size_mul in self.ores:
            ore = B.BY_NAME[name].id
            lo, hi = ore_depth(name)
            for _ in range(max(1, int(tries * 3))):
                x = int(rng.integers(1, CHUNK_X - 1))
                z = int(rng.integers(1, CHUNK_Z - 1))
                y = int(rng.integers(lo, hi))
                n = int(rng.integers(3, 3 + int(4 * size_mul)))
                for _ in range(n):
                    xx = min(max(x + int(rng.integers(-1, 2)), 0), CHUNK_X - 1)
                    yy = min(max(y + int(rng.integers(-1, 2)), 1), WORLD_H - 1)
                    zz = min(max(z + int(rng.integers(-1, 2)), 0), CHUNK_Z - 1)
                    if blk[xx, yy, zz] == stone:
                        blk[xx, yy, zz] = ore

    def _place_trees(self, chunk: Chunk, height, snowy, desert, rocky, moist, rng):
        """种橡树。树冠完全落在本区块内（位置限制在 2..13），避免跨区块被切断。"""
        grass = B.BY_NAME["grass_block"].id
        log = B.BY_NAME["oak_log"].id
        leaf = B.BY_NAME["oak_leaves"].id
        blk = chunk.blocks
        # 湿度越高树越多（森林），沙漠/雪原/高山不长树
        m = float(moist.mean())
        tries = 6 if m > 0.56 else (3 if m > 0.46 else 1)
        for _ in range(tries):
            x = int(rng.integers(2, 14))
            z = int(rng.integers(2, 14))
            if desert[x, z] or snowy[x, z] or rocky[x, z]:
                continue
            h = int(height[x, z])
            if h <= SEA_LEVEL + 1 or h >= WORLD_H - 16:
                continue
            if blk[x, h, z] != grass:
                continue
            trunk = int(rng.integers(4, 7))
            for i in range(trunk):
                if h + i < WORLD_H:
                    blk[x, h + i, z] = log
            top = h + trunk
            for dy in range(-2, 2):
                r = 2 if dy < 1 else 1
                for dx in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        if abs(dx) == r and abs(dz) == r and rng.random() < 0.6:
                            continue
                        yy = top + dy
                        xx, zz = x + dx, z + dz
                        if (0 <= xx < CHUNK_X and 0 <= zz < CHUNK_Z
                                and 0 <= yy < WORLD_H and blk[xx, yy, zz] == 0):
                            blk[xx, yy, zz] = leaf
        return chunk


def ore_depth(name):
    return {
        "coal_ore": (6, 96),
        "iron_ore": (4, 72),
        "gold_ore": (4, 34),
        "diamond_ore": (3, 18),
    }.get(name, (4, 64))
