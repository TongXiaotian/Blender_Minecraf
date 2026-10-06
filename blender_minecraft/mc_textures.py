"""程序化生成《我的世界》风格的像素贴图图集。

不依赖任何外部图片，全部用 numpy 现场画出来，画风刻意模仿原版：
低分辨率色块噪声 + 有限调色板 + 每个方块 16x16 像素。

最终产出一张 256x256 的 RGBA 图集（16x16 个 16px 贴图），
由 mc_textures.build_atlas() 返回 (numpy uint8 数组, 贴图名顺序表)。
"""
from __future__ import annotations

import math

import numpy as np

from .mc_const import ATLAS_COLS, ATLAS_PX, ATLAS_ROWS, TILE_PX

# 所有贴图名（顺序 == 图集里的格子序号）
TILE_NAMES = [
    "stone", "dirt", "grass_top", "grass_side", "cobblestone", "oak_planks",
    "bedrock", "sand", "gravel", "oak_log_side", "oak_log_top", "oak_leaves",
    "water", "glass", "coal_ore", "iron_ore",
    "gold_ore", "diamond_ore", "bricks", "snow",
    "ice", "sandstone", "obsidian", "glowstone",
    "crafting_table_top", "crafting_table_side", "furnace_side", "furnace_top",
    "tnt_side", "tnt_top", "iron_block", "gold_block",
    "diamond_block", "bookshelf", "netherrack", "stone_bricks",
    # ---- 以下是 HUD/UI 用的贴图 ----
    "heart_full", "heart_half", "heart_empty",
    "food_full", "food_half", "food_empty",
    "crack_0", "crack_1", "crack_2", "crack_3",
    "slot", "xp_icon",
]
TILE_INDEX = {name: i for i, name in enumerate(TILE_NAMES)}


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def _rgb(*c) -> np.ndarray:
    return np.array(c, dtype=np.float32)


def _shade_tex(rng, shades, cell=2, alpha=255):
    """低分辨率随机色块噪声：很接近原版石头/泥土那种“颗粒感”。"""
    n = TILE_PX // cell + 1
    grid = rng.integers(0, len(shades), size=(n, n))
    idx = np.repeat(np.repeat(grid, cell, 0), cell, 1)[:TILE_PX, :TILE_PX]
    pal = np.array(shades, dtype=np.float32)
    img = pal[idx]                                     # (16,16,3)
    out = np.empty((TILE_PX, TILE_PX, 4), dtype=np.float32)
    out[..., :3] = img
    out[..., 3] = alpha
    return out


def _flood(img, color, alpha=255):
    img[..., 0], img[..., 1], img[..., 2] = color
    img[..., 3] = alpha
    return img


def _rect(img, x0, y0, x1, y1, color, alpha=255):
    """左闭右开矩形填充（y 向下）。"""
    img[y0:y1, x0:x1, 0] = color[0]
    img[y0:y1, x0:x1, 1] = color[1]
    img[y0:y1, x0:x1, 2] = color[2]
    img[y0:y1, x0:x1, 3] = alpha
    return img


def _px(img, x, y, color, alpha=255):
    if 0 <= x < TILE_PX and 0 <= y < TILE_PX:
        img[y, x, 0], img[y, x, 1], img[y, x, 2] = color
        img[y, x, 3] = alpha
    return img


def _disc(img, cx, cy, r, colors, rng, alpha=255, jitter=True):
    """画一团矿脉/斑点。"""
    pal = np.array(colors, dtype=np.float32)
    for y in range(TILE_PX):
        for x in range(TILE_PX):
            dx, dy = x - cx + 0.5, y - cy + 0.5
            d = (dx * dx + dy * dy) ** 0.5
            if jitter:
                d += rng.random() * 0.9 - 0.45
            if d <= r:
                c = pal[rng.integers(0, len(pal))]
                _px(img, x, y, c, alpha)
    return img


# --------------------------------------------------------------------------
# 各方块贴图
# --------------------------------------------------------------------------
def _t_stone(rng):
    return _shade_tex(rng, [(104, 104, 104), (116, 116, 116), (126, 126, 126),
                            (136, 136, 136), (146, 146, 146)], cell=2)


def _t_dirt(rng):
    return _shade_tex(rng, [(86, 58, 36), (104, 72, 46), (124, 88, 58),
                            (140, 100, 66), (154, 116, 82)], cell=2)


def _t_grass_top(rng):
    img = _shade_tex(rng, [(76, 138, 44), (88, 152, 50), (98, 166, 56),
                           (110, 178, 64), (120, 188, 72)], cell=2)
    # 加一点更细的杂色，避免看起来太"整块"
    for _ in range(36):
        x, y = rng.integers(0, TILE_PX, 2)
        c = (74 + rng.integers(0, 60), 130 + rng.integers(0, 70), 40 + rng.integers(0, 40))
        _px(img, int(x), int(y), c)
    return img


def _t_grass_side(rng):
    img = _t_dirt(rng)
    for x in range(TILE_PX):
        depth = 3 + int(rng.integers(0, 3))
        for y in range(depth):
            c = (74 + int(rng.integers(0, 46)), 128 + int(rng.integers(0, 56)),
                 40 + int(rng.integers(0, 34)))
            _px(img, x, y, c)
        # 边缘多一层稍暗的绿，形成锯齿
        _px(img, x, depth, (66 + int(rng.integers(0, 30)), 116 + int(rng.integers(0, 40)),
                            36 + int(rng.integers(0, 24))))
    return img


def _t_cobblestone(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (120, 120, 120))
    pal = [(96, 96, 96), (108, 108, 108), (122, 122, 122), (136, 136, 136), (150, 150, 150)]
    # 随机石块
    for _ in range(26):
        w = int(rng.integers(3, 6))
        h = int(rng.integers(2, 5))
        x0 = int(rng.integers(0, TILE_PX))
        y0 = int(rng.integers(0, TILE_PX))
        c = pal[int(rng.integers(0, len(pal)))]
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                if 0 <= x < TILE_PX and 0 <= y < TILE_PX:
                    _px(img, x, y, c)
    # 石块之间的深色缝隙
    for _ in range(14):
        x0 = int(rng.integers(0, TILE_PX))
        y0 = int(rng.integers(0, TILE_PX))
        if rng.random() < 0.5:
            for x in range(x0, min(TILE_PX, x0 + int(rng.integers(3, 9)))):
                _px(img, x, y0, (74, 74, 74))
        else:
            for y in range(y0, min(TILE_PX, y0 + int(rng.integers(3, 9)))):
                _px(img, x0, y, (74, 74, 74))
    return img


def _t_oak_planks(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (162, 130, 78))
    bands = [(150, 118, 68), (162, 130, 78), (172, 140, 88), (156, 124, 74)]
    for b in range(4):
        c = bands[b]
        _rect(img, 0, b * 4, TILE_PX, b * 4 + 4, c)
        # 板与板之间的接缝
        _rect(img, 0, b * 4 + 3, TILE_PX, b * 4 + 4, (116, 88, 50))
        # 木纹
        for _ in range(2):
            y = b * 4 + int(rng.integers(0, 3))
            x0 = int(rng.integers(0, TILE_PX))
            for x in range(x0, min(TILE_PX, x0 + int(rng.integers(3, 10)))):
                _px(img, x, y, (140, 108, 62))
        # 竖向接缝
        jx = int(rng.integers(2, TILE_PX - 2))
        _rect(img, jx, b * 4, jx + 1, b * 4 + 4, (128, 98, 56))
    return img


def _t_bedrock(rng):
    return _shade_tex(rng, [(34, 34, 34), (56, 56, 56), (78, 78, 78),
                            (98, 98, 98), (120, 120, 120)], cell=1)


def _t_sand(rng):
    return _shade_tex(rng, [(206, 192, 148), (214, 201, 158), (222, 210, 168),
                            (230, 219, 178), (238, 228, 190)], cell=1)


def _t_gravel(rng):
    return _shade_tex(rng, [(84, 80, 76), (108, 104, 100), (134, 130, 124),
                            (158, 152, 144), (178, 172, 164)], cell=1)


def _t_oak_log_side(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (104, 78, 46))
    stripes = [(84, 62, 36), (96, 70, 42), (104, 78, 46), (116, 88, 52), (128, 98, 60)]
    x = 0
    while x < TILE_PX:
        w = int(rng.integers(1, 4))
        c = stripes[int(rng.integers(0, len(stripes)))]
        _rect(img, x, 0, min(TILE_PX, x + w), TILE_PX, c)
        x += w
    # 深色木纹线
    for _ in range(4):
        x0 = int(rng.integers(0, TILE_PX))
        _rect(img, x0, 0, x0 + 1, TILE_PX, (72, 52, 30))
    return img


def _t_oak_log_top(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (104, 78, 46))
    ring = [(150, 120, 74), (128, 98, 58), (150, 120, 74), (112, 84, 48),
            (150, 120, 74), (128, 98, 58), (166, 136, 88)]
    cx = cy = TILE_PX / 2 - 0.5
    for y in range(TILE_PX):
        for x in range(TILE_PX):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            k = int(d) % len(ring)
            _px(img, x, y, ring[k])
    # 树皮外圈
    for i in range(TILE_PX):
        _px(img, i, 0, (84, 62, 36))
        _px(img, i, TILE_PX - 1, (84, 62, 36))
        _px(img, 0, i, (84, 62, 36))
        _px(img, TILE_PX - 1, i, (84, 62, 36))
    return img


def _t_oak_leaves(rng):
    img = _shade_tex(rng, [(38, 92, 28), (46, 108, 34), (56, 122, 40),
                           (66, 136, 48), (78, 150, 56)], cell=1)
    # 挖几个"洞"（用更暗的绿，保持不透明，等同原版的"流畅"画质）
    for _ in range(26):
        x, y = (int(rng.integers(0, TILE_PX)) for _ in range(2))
        _px(img, x, y, (26, 68, 22))
    return img


def _t_water(rng):
    img = _shade_tex(rng, [(52, 96, 190), (58, 106, 200), (64, 116, 210),
                           (70, 126, 220)], cell=2, alpha=210)
    # 波纹
    for _ in range(3):
        y0 = int(rng.integers(0, TILE_PX))
        for x in range(TILE_PX):
            if (x // 2) % 2 == 0:
                _px(img, x, y0, (86, 146, 230), 200)
    return img


def _t_glass(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (0, 0, 0), 0)
    edge = (206, 232, 240)
    for i in range(TILE_PX):
        _px(img, i, 0, edge, 235)
        _px(img, i, TILE_PX - 1, edge, 235)
        _px(img, 0, i, edge, 235)
        _px(img, TILE_PX - 1, i, edge, 235)
    # 高光斜线
    for i in range(2, 7):
        _px(img, i, TILE_PX - i, (255, 255, 255), 150)
        _px(img, i + 1, TILE_PX - i, (255, 255, 255), 110)
    return img


def _t_ore(rng, colors):
    img = _t_stone(rng)
    return _disc(img, rng.integers(4, 12), rng.integers(4, 12), 2.4, colors, rng)


def _t_coal_ore(rng):
    return _t_ore(rng, [(24, 24, 24), (40, 40, 40), (56, 56, 56)])


def _t_iron_ore(rng):
    return _t_ore(rng, [(186, 150, 122), (206, 172, 144), (222, 190, 164)])


def _t_gold_ore(rng):
    return _t_ore(rng, [(214, 176, 46), (238, 202, 62), (250, 226, 106)])


def _t_diamond_ore(rng):
    return _t_ore(rng, [(78, 216, 214), (110, 240, 236), (156, 250, 248)])


def _t_bricks(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (186, 178, 168))
    pal = [(138, 74, 56), (150, 82, 62), (162, 92, 70), (126, 66, 50)]
    for row in range(4):
        y0 = row * 4
        offset = 0 if row % 2 == 0 else 4
        x = -8 + offset
        while x < TILE_PX:
            c = pal[int(rng.integers(0, len(pal)))]
            _rect(img, max(0, x), y0, min(TILE_PX, x + 7), y0 + 3, c)
            x += 8
    return img


def _t_snow(rng):
    return _shade_tex(rng, [(236, 240, 246), (242, 246, 250), (248, 251, 254),
                            (252, 253, 255)], cell=2)


def _t_ice(rng):
    img = _shade_tex(rng, [(126, 176, 226), (140, 190, 236), (156, 204, 244),
                           (172, 216, 250)], cell=2, alpha=205)
    for _ in range(4):
        x0 = int(rng.integers(0, TILE_PX - 5))
        y0 = int(rng.integers(0, TILE_PX - 5))
        for i in range(5):
            _px(img, x0 + i, y0 + i, (210, 236, 255), 225)
    return img


def _t_sandstone(rng):
    img = _t_sand(rng)
    for y in (0, 1, 8, 9, 15):
        for x in range(TILE_PX):
            _px(img, x, y, (196, 182, 138))
    return img


def _t_obsidian(rng):
    img = _shade_tex(rng, [(14, 10, 22), (22, 16, 34), (30, 22, 44)], cell=2)
    for _ in range(10):
        x, y = (int(rng.integers(0, TILE_PX)) for _ in range(2))
        _px(img, x, y, (74, 48, 108))
    return img


def _t_glowstone(rng):
    img = _shade_tex(rng, [(206, 166, 62), (226, 190, 84), (240, 210, 110)], cell=2)
    for _ in range(7):
        _disc(img, rng.integers(2, 14), rng.integers(2, 14), 1.6,
              [(250, 236, 170), (255, 246, 200)], rng)
    return img


def _block_face(rng, base, light, dark):
    """金属/宝石块那种带高光方格的贴图。"""
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), base)
    for by in range(0, TILE_PX, 8):
        for bx in range(0, TILE_PX, 8):
            _rect(img, bx, by, bx + 4, by + 4, light)
            _rect(img, bx + 4, by + 4, bx + 8, by + 8, dark)
    return img


def _t_crafting_top(rng):
    img = _t_oak_planks(rng)
    for i in range(TILE_PX):
        _px(img, i, 0, (96, 72, 40))
        _px(img, i, 1, (110, 82, 46))
        _px(img, i, TILE_PX - 1, (96, 72, 40))
    for gx in (5, 10):
        _rect(img, gx, 2, gx + 1, TILE_PX - 1, (110, 84, 48))
    for gy in (5, 10):
        _rect(img, 1, gy, TILE_PX - 1, gy + 1, (110, 84, 48))
    return img


def _t_crafting_side(rng):
    img = _t_oak_planks(rng)
    _rect(img, 2, 2, 14, 7, (126, 96, 54))
    _rect(img, 3, 3, 13, 6, (168, 138, 84))
    for i in range(2, 14):
        _px(img, i, 8, (110, 84, 48))
        _px(img, i, 11, (110, 84, 48))
    return img


def _t_furnace_side(rng):
    img = _t_stone(rng)
    for i in range(TILE_PX):
        _px(img, 0, i, (92, 92, 92))
        _px(img, i, 0, (100, 100, 100))
        _px(img, i, TILE_PX - 1, (88, 88, 88))
        _px(img, TILE_PX - 1, i, (92, 92, 92))
    _rect(img, 4, 5, 12, 13, (54, 52, 52))
    _rect(img, 5, 6, 11, 12, (34, 32, 32))
    return img


def _t_furnace_top(rng):
    img = _t_stone(rng)
    _rect(img, 4, 4, 12, 12, (100, 100, 100))
    _rect(img, 5, 5, 11, 11, (78, 78, 78))
    return img


def _t_tnt_side(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (178, 56, 46))
    for _ in range(20):
        x, y = (int(rng.integers(0, TILE_PX)) for _ in range(2))
        _px(img, x, y, (150, 42, 36))
    _rect(img, 0, 5, TILE_PX, 11, (232, 232, 228))
    letters = [(3, 6), (4, 6), (5, 6), (3, 8), (5, 8), (3, 10), (4, 10), (5, 10),
               (8, 6), (8, 7), (8, 8), (9, 9), (10, 9),
               (12, 6), (13, 6), (12, 7), (12, 8), (13, 8)]
    for (x, y) in letters:
        _rect(img, x, y, x + 1, y + 1, (60, 40, 36))
    return img


def _t_tnt_top(rng):
    img = _flood(np.zeros((TILE_PX, TILE_PX, 4), np.float32), (178, 56, 46))
    _rect(img, 0, 0, TILE_PX, TILE_PX, (178, 56, 46))
    _rect(img, 2, 2, 14, 14, (208, 208, 204))
    _rect(img, 3, 3, 13, 13, (178, 56, 46))
    _rect(img, 6, 6, 10, 10, (72, 52, 40))
    _px(img, 8, 5, (40, 40, 40))
    return img


def _t_bookshelf(rng):
    img = _t_oak_planks(rng)
    _rect(img, 0, 3, TILE_PX, 6, (150, 120, 72))
    _rect(img, 0, 10, TILE_PX, 13, (150, 120, 72))
    pal = [(160, 60, 52), (70, 96, 160), (196, 176, 72), (84, 150, 78), (150, 90, 170)]
    x = 0
    while x < TILE_PX:
        w = int(rng.integers(1, 3))
        c = pal[int(rng.integers(0, len(pal)))]
        _rect(img, x, 3, min(TILE_PX, x + w), 6, c)
        c = pal[int(rng.integers(0, len(pal)))]
        _rect(img, x, 10, min(TILE_PX, x + w), 13, c)
        x += w
    _rect(img, 0, 0, TILE_PX, 3, (128, 98, 56))
    _rect(img, 0, 13, TILE_PX, TILE_PX, (128, 98, 56))
    return img


def _t_netherrack(rng):
    return _shade_tex(rng, [(88, 30, 30), (104, 38, 36), (120, 46, 42),
                            (72, 24, 26)], cell=1)


def _t_stone_bricks(rng):
    img = _t_stone(rng)
    for y in (0, 8):
        _rect(img, 0, y, TILE_PX, y + 1, (78, 78, 78))
    for x in (0, 8):
        _rect(img, x, 0, x + 1, 8, (78, 78, 78))
    _rect(img, 4, 8, 5, TILE_PX, (78, 78, 78))
    _rect(img, 12, 8, 13, TILE_PX, (78, 78, 78))
    return img


def _mask_tile(rows, palette, scale=2, ox=0, oy=1):
    """用字符画生成像素贴图（'X'/'O'/'H'... 对应 palette 里的颜色，'.' 透明）。"""
    img = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    for ry, row in enumerate(rows):
        for rx, ch in enumerate(row):
            if ch == "." or ch not in palette:
                continue
            color = palette[ch]
            for sy in range(scale):
                for sx in range(scale):
                    _px(img, ox + rx * scale + sx, oy + ry * scale + sy, color)
    return img


_HEART_MASK = (
    ".XX..XX.",
    "XHHXXOOX",
    "XHHOOOOX",
    "XOOOOOOX",
    ".XOOOOX.",
    "..XOOX..",
    "...XX...",
)
_HEART_PALETTE = {
    "X": (120, 22, 22),
    "O": (206, 44, 44),
    "H": (255, 132, 132),
}
_HEART_EMPTY = {
    "X": (58, 58, 58),
    "O": (92, 92, 92),
    "H": (128, 128, 128),
}


def _t_heart_full(rng):
    return _mask_tile(_HEART_MASK, _HEART_PALETTE)


def _t_heart_empty(rng):
    return _mask_tile(_HEART_MASK, _HEART_EMPTY)


def _t_heart_half(rng):
    full = _mask_tile(_HEART_MASK, _HEART_PALETTE)
    empty = _mask_tile(_HEART_MASK, _HEART_EMPTY)
    out = empty.copy()
    out[:, :TILE_PX // 2] = full[:, :TILE_PX // 2]
    return out


def _t_food_full(rng):
    img = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    # 骨头
    _rect(img, 3, 10, 7, 13, (232, 232, 226))
    _rect(img, 2, 9, 5, 11, (240, 240, 236))
    _rect(img, 5, 12, 8, 14, (240, 240, 236))
    # 肉
    _disc(img, 10, 6, 4.6, [(150, 78, 44), (172, 96, 56), (188, 112, 68)], rng)
    _disc(img, 9, 5, 2.6, [(206, 140, 92), (196, 128, 82)], rng)
    return img


def _t_food_empty(rng):
    img = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    _rect(img, 3, 10, 7, 13, (96, 96, 96))
    _rect(img, 2, 9, 5, 11, (110, 110, 110))
    _rect(img, 5, 12, 8, 14, (110, 110, 110))
    _disc(img, 10, 6, 4.6, [(78, 78, 78), (92, 92, 92)], rng)
    return img


def _t_food_half(rng):
    full = _t_food_full(rng)
    empty = _t_food_empty(rng)
    out = empty.copy()
    out[:, :TILE_PX // 2] = full[:, :TILE_PX // 2]
    return out


def _t_crack(rng, strength):
    """挖掘裂纹（越挖越明显）。"""
    img = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    cx = cy = TILE_PX / 2.0
    n = 3 + strength * 3
    for _ in range(n):
        ang = rng.random() * math.tau
        x, y = cx, cy
        steps = 3 + strength * 4 + int(rng.random() * 4)
        for i in range(steps):
            ang += (rng.random() - 0.5) * 0.9
            x += math.cos(ang) * 1.4
            y += math.sin(ang) * 1.4
            if not (0 <= x < TILE_PX and 0 <= y < TILE_PX):
                break
            _px(img, int(x), int(y), (0, 0, 0), 90 + strength * 45)
            if rng.random() < 0.35 + 0.15 * strength:
                _px(img, int(x) + 1, int(y), (0, 0, 0), 60 + strength * 40)
    return img


def _t_slot(rng):
    img = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    _rect(img, 0, 0, TILE_PX, TILE_PX, (139, 139, 139), 200)
    _rect(img, 0, 0, TILE_PX, 1, (55, 55, 55), 235)
    _rect(img, 0, 0, 1, TILE_PX, (55, 55, 55), 235)
    _rect(img, 1, 1, TILE_PX - 1, 2, (85, 85, 85), 220)
    _rect(img, 1, 1, 2, TILE_PX - 1, (85, 85, 85), 220)
    _rect(img, TILE_PX - 1, 1, TILE_PX, TILE_PX, (245, 245, 245), 220)
    _rect(img, 1, TILE_PX - 1, TILE_PX, TILE_PX, (245, 245, 245), 220)
    return img


def _t_xp_icon(rng):
    img = np.zeros((TILE_PX, TILE_PX, 4), dtype=np.float32)
    _disc(img, 8, 8, 5.0, [(110, 210, 60), (150, 235, 80)], rng)
    _disc(img, 6, 6, 2.0, [(220, 255, 160)], rng)
    return img


_BUILDERS = {
    "stone": _t_stone,
    "dirt": _t_dirt,
    "grass_top": _t_grass_top,
    "grass_side": _t_grass_side,
    "cobblestone": _t_cobblestone,
    "oak_planks": _t_oak_planks,
    "bedrock": _t_bedrock,
    "sand": _t_sand,
    "gravel": _t_gravel,
    "oak_log_side": _t_oak_log_side,
    "oak_log_top": _t_oak_log_top,
    "oak_leaves": _t_oak_leaves,
    "water": _t_water,
    "glass": _t_glass,
    "coal_ore": _t_coal_ore,
    "iron_ore": _t_iron_ore,
    "gold_ore": _t_gold_ore,
    "diamond_ore": _t_diamond_ore,
    "bricks": _t_bricks,
    "snow": _t_snow,
    "ice": _t_ice,
    "sandstone": _t_sandstone,
    "obsidian": _t_obsidian,
    "glowstone": _t_glowstone,
    "crafting_table_top": _t_crafting_top,
    "crafting_table_side": _t_crafting_side,
    "furnace_side": _t_furnace_side,
    "furnace_top": _t_furnace_top,
    "tnt_side": _t_tnt_side,
    "tnt_top": _t_tnt_top,
    "iron_block": lambda r: _block_face(r, (206, 206, 206), (232, 232, 232), (176, 176, 176)),
    "gold_block": lambda r: _block_face(r, (240, 208, 74), (255, 236, 128), (206, 172, 46)),
    "diamond_block": lambda r: _block_face(r, (94, 224, 218), (150, 246, 242), (62, 190, 186)),
    "bookshelf": _t_bookshelf,
    "netherrack": _t_netherrack,
    "stone_bricks": _t_stone_bricks,
    # ---- HUD ----
    "heart_full": _t_heart_full,
    "heart_half": _t_heart_half,
    "heart_empty": _t_heart_empty,
    "food_full": _t_food_full,
    "food_half": _t_food_half,
    "food_empty": _t_food_empty,
    "crack_0": lambda r: _t_crack(r, 0),
    "crack_1": lambda r: _t_crack(r, 1),
    "crack_2": lambda r: _t_crack(r, 2),
    "crack_3": lambda r: _t_crack(r, 3),
    "slot": _t_slot,
    "xp_icon": _t_xp_icon,
}


def build_atlas(seed: int = 20240501):
    """生成 256x256 RGBA 图集（uint8，sRGB 编码值）。"""
    rng = np.random.default_rng(seed)
    atlas = np.zeros((ATLAS_PX, ATLAS_PX, 4), dtype=np.float32)
    for i, name in enumerate(TILE_NAMES):
        col, row = i % ATLAS_COLS, i // ATLAS_COLS
        tile = _BUILDERS[name](rng)
        y0, x0 = row * TILE_PX, col * TILE_PX
        atlas[y0:y0 + TILE_PX, x0:x0 + TILE_PX] = tile
    return np.clip(atlas, 0, 255).astype(np.uint8)


def tile_uv(tile_index: int):
    """返回贴图在图集中的 UV 范围 (u0, v0, u1, v1)，v 轴按 Blender 约定向上。"""
    col = tile_index % ATLAS_COLS
    row = tile_index // ATLAS_COLS
    u0 = col / ATLAS_COLS
    u1 = (col + 1) / ATLAS_COLS
    v1 = 1.0 - row / ATLAS_ROWS
    v0 = 1.0 - (row + 1) / ATLAS_ROWS
    return u0, v0, u1, v1
