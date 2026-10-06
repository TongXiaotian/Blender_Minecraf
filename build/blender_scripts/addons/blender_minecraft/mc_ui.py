"""HUD / 界面：全部用 Blender 的 gpu + blf 画在 3D 视图之上（Blender 5.2 API）。

坐标约定：布局用"Minecraft 界面单位"（缩放前像素，基准 320x240），
内部乘 ui.scale 变成真实像素；原点在左下角（POST_PIXEL 本来就是左下角）。

绘制分三趟，保证层次：
  1) 纯色矩形（一个批次，按提交顺序）
  2) 贴图矩形 + 伪 3D 方块图标
  3) 文字（blf 立即模式，永远在最上层）
"""
from __future__ import annotations

import os

import blf
import gpu
from gpu_extras.batch import batch_for_shader

from . import mc_blocks as B
from .mc_textures import TILE_INDEX, tile_uv

# ---------------------------------------------------------------------------
# 配色（尽量贴近原版）
# ---------------------------------------------------------------------------
C_TEXT = (1.0, 1.0, 1.0, 1.0)
C_SHADOW = (0.0, 0.0, 0.0, 0.85)
C_PANEL = (0.0, 0.0, 0.0, 0.48)
C_SLOT = (0.20, 0.20, 0.20, 0.55)
C_SELECT = (1.0, 1.0, 1.0, 0.92)
C_INV_PANEL = (0.78, 0.78, 0.78, 1.0)
C_INV_BORDER = (0.16, 0.16, 0.16, 1.0)
C_TITLE = (0.24, 0.24, 0.24, 1.0)
C_BTN = (0.42, 0.42, 0.42, 0.95)
C_BTN_HOVER = (0.56, 0.62, 0.56, 0.98)
C_BTN_BORDER = (0.88, 0.88, 0.88, 1.0)
C_TOOLTIP_BG = (0.07, 0.02, 0.12, 0.95)
C_TOOLTIP_BD = (0.35, 0.12, 0.55, 1.0)
C_XP_BG = (0.0, 0.0, 0.0, 0.75)
C_XP_FG = (0.55, 0.90, 0.15, 1.0)

_FONTS = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/Deng.ttf", "C:/Windows/Fonts/msjh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_FONT_CACHE: list = []


def load_cjk_font():
    """找一个支持中文的字体给 blf 用；找不到就返回 0（默认位图字体）。"""
    if _FONT_CACHE:
        return _FONT_CACHE[0]
    fid = 0
    for path in _FONTS:
        if os.path.exists(path):
            try:
                fid = blf.load(path)
                break
            except Exception:
                continue
    _FONT_CACHE.append(fid)
    return fid


def _mul(tint, k):
    return (tint[0] * k, tint[1] * k, tint[2] * k, tint[3])


class UI:
    """立即模式界面绘制器。"""

    def __init__(self):
        self.scale = 2
        self.region_w = 800
        self.region_h = 600
        self.font = 0
        self._flat_shader = None
        self._img_shader = None
        self._tex = None
        self._tile_batches: dict[int, object] = {}
        self._flat_pos: list = []
        self._flat_col: list = []
        self._flat_idx: list = []
        self._rect_icons: list = []
        self._poly_icons: list = []
        self._text_calls: list = []
        self._ready = False

    # ------------------------------------------------------------------
    def ensure(self, atlas_image):
        if self._ready:
            return
        self._flat_shader = gpu.shader.from_builtin("FLAT_COLOR")
        self._img_shader = gpu.shader.from_builtin("IMAGE_COLOR")
        self._tex = gpu.texture.from_image(atlas_image)
        self.font = load_cjk_font()
        self._ready = True

    @property
    def ready(self):
        return self._ready

    def set_region(self, width, height):
        self.region_w, self.region_h = int(width), int(height)
        self.scale = max(1, min(int(width / 320), int(height / 240)))

    @property
    def w(self):
        return self.region_w / self.scale

    @property
    def h(self):
        return self.region_h / self.scale

    # ------------------------------------------------------------------
    def begin(self):
        self._flat_pos.clear()
        self._flat_col.clear()
        self._flat_idx.clear()
        self._rect_icons.clear()
        self._poly_icons.clear()
        self._text_calls.clear()
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        gpu.state.depth_mask_set(False)

    def end(self):
        self._draw_flat()
        self._draw_icons()
        self._draw_text()

    # ---------- 纯色 ----------
    def rect(self, x, y, w, h, rgba):
        s = self.scale
        self.rect_px(x * s, y * s, (x + w) * s, (y + h) * s, rgba)

    def rect_px(self, x0, y0, x1, y1, rgba):
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        base = len(self._flat_pos)
        self._flat_pos.extend([(x0, y0, 0.0), (x1, y0, 0.0),
                               (x1, y1, 0.0), (x0, y1, 0.0)])
        self._flat_col.extend([rgba] * 4)
        self._flat_idx.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])

    def outline(self, x, y, w, h, t, rgba):
        self.rect(x, y, w, t, rgba)
        self.rect(x, y + h - t, w, t, rgba)
        self.rect(x, y + t, t, max(0.0, h - 2 * t), rgba)
        self.rect(x + w - t, y + t, t, max(0.0, h - 2 * t), rgba)

    # ---------- 贴图 ----------
    def icon(self, tile, x, y, w, h, tint=(1.0, 1.0, 1.0, 1.0)):
        self._rect_icons.append((int(tile), x, y, w, h, tint))

    def poly_icon(self, tile, pts, tint=(1.0, 1.0, 1.0, 1.0)):
        self._poly_icons.append((int(tile), pts, tint))

    def text(self, content, x, y, size=8, rgba=C_TEXT, shadow=True, align="left"):
        self._text_calls.append((str(content), x, y, size, rgba, shadow, align))

    def text_width(self, content, size=8):
        blf.size(self.font, max(1, int(size * self.scale)))
        return blf.dimensions(self.font, str(content))[0] / self.scale

    # ------------------------------------------------------------------
    def _draw_flat(self):
        if not self._flat_pos:
            return
        batch = batch_for_shader(self._flat_shader, "TRIS",
                                 {"pos": self._flat_pos, "color": self._flat_col},
                                 indices=self._flat_idx)
        batch.draw(self._flat_shader)

    def _tile_batch(self, tile):
        b = self._tile_batches.get(tile)
        if b is None:
            u0, v0, u1, v1 = tile_uv(tile)
            pos = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
            uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            b = batch_for_shader(self._img_shader, "TRIS", {"pos": pos, "texCoord": uv},
                                 indices=[(0, 1, 2), (2, 3, 0)])
            self._tile_batches[tile] = b
        return b

    def _draw_icons(self):
        sh = self._img_shader
        sh.uniform_sampler("image", self._tex)
        s = self.scale
        for tile, x, y, w, h, tint in self._rect_icons:
            with gpu.matrix.push_pop():
                gpu.matrix.translate((x * s, y * s))
                gpu.matrix.scale((w * s, h * s))
                sh.uniform_float("color", tint)
                self._tile_batch(tile).draw(sh)
        for tile, pts, tint in self._poly_icons:
            u0, v0, u1, v1 = tile_uv(tile)
            pos = [(p[0] * s, p[1] * s, 0.0) for p in pts]
            uv = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            batch = batch_for_shader(sh, "TRIS", {"pos": pos, "texCoord": uv},
                                     indices=[(0, 1, 2), (0, 2, 3)])
            sh.uniform_float("color", tint)
            batch.draw(sh)

    def _draw_text(self):
        s = self.scale
        for content, x, y, size, rgba, shadow, align in self._text_calls:
            blf.size(self.font, max(1, int(size * s)))
            w = blf.dimensions(self.font, content)[0]
            px = x * s
            if align == "center":
                px -= w / 2.0
            elif align == "right":
                px -= w
            py = y * s
            if shadow:
                blf.color(self.font, *C_SHADOW)
                blf.position(self.font, px + s, py - s, 0)
                blf.draw(self.font, content)
            blf.color(self.font, *rgba)
            blf.position(self.font, px, py, 0)
            blf.draw(self.font, content)

    # ------------------------------------------------------------------
    # 伪 3D 方块图标（等距立方体：顶面 + 左右侧面）
    # ------------------------------------------------------------------
    def block_icon(self, block, x, y, size, tint=(1.0, 1.0, 1.0, 1.0)):
        w = h = size
        cx = x + w / 2.0
        p_T = (cx, y + h)
        p_L = (x, y + h * 0.75)
        p_R = (x + w, y + h * 0.75)
        p_M = (cx, y + h * 0.5)
        p_BL = (x, y + h * 0.25)
        p_BR = (x + w, y + h * 0.25)
        p_B = (cx, y)
        self.poly_icon(block.tiles[2], (p_L, p_T, p_R, p_M), _mul(tint, 1.0))
        self.poly_icon(block.tiles[0], (p_L, p_M, p_B, p_BL), _mul(tint, 0.62))
        self.poly_icon(block.tiles[4], (p_M, p_R, p_BR, p_B), _mul(tint, 0.82))

    # ------------------------------------------------------------------
    # HUD 组件
    # ------------------------------------------------------------------
    def crosshair(self, cx, cy):
        t = 1.0
        self.rect(cx - 5, cy - t / 2, 10, t, (1, 1, 1, 0.85))
        self.rect(cx - t / 2, cy - 5, t, 10, (1, 1, 1, 0.85))

    def hotbar(self, inv, cx, bottom=3.0):
        x0, bottom, slot, total_w = hotbar_layout(cx, bottom)
        self.rect(x0 - 1, bottom - 1, total_w + 2, slot + 2, C_PANEL)
        for i in range(9):
            sx = x0 + 1 + i * slot
            self.rect(sx, bottom, slot, slot, C_SLOT)
            self.slot_icon(inv.slots[i], sx, bottom, slot, inv.creative)
        sel = x0 + 1 + inv.selected * slot
        self.outline(sel - 1, bottom - 1, slot + 2, slot + 2, 1.0, C_SELECT)

    def slot_icon(self, stack, x, y, slot, creative=False):
        if stack is None or getattr(stack, "empty", True):
            return
        blk = B.BY_NAME.get(stack.name)
        if blk is not None and blk.id != 0:
            self.block_icon(blk, x + 2, y + 2, slot - 4)
        if stack.count > 1:
            self.text(str(stack.count), x + slot - 2, y + 2, 7, C_TEXT, True, "right")

    def item_name(self, name, cx, y, size=8):
        if not name:
            return
        w = self.text_width(name, size)
        self.rect(cx - w / 2 - 3, y - 2, w + 6, size + 4, (0, 0, 0, 0.6))
        self.text(name, cx, y, size, C_TEXT, True, "center")

    def health(self, hp, x, y, size=9, spacing=8):
        for i in range(10):
            val = hp - i * 2
            tile = (TILE_INDEX["heart_full"] if val >= 2 else
                    TILE_INDEX["heart_half"] if val >= 1 else
                    TILE_INDEX["heart_empty"])
            self.icon(tile, x + i * spacing, y, size, size)

    def hunger_bar(self, hunger, x_right, y, size=9, spacing=8):
        for i in range(10):
            val = hunger - i * 2
            tile = (TILE_INDEX["food_full"] if val >= 2 else
                    TILE_INDEX["food_half"] if val >= 1 else
                    TILE_INDEX["food_empty"])
            self.icon(tile, x_right - size - i * spacing, y, size, size)

    def xp_bar(self, cx, y, width, progress, level):
        self.rect(cx - width / 2, y, width, 5, C_XP_BG)
        self.rect(cx - width / 2 + 1, y + 1, (width - 2) * max(0.0, min(1.0, progress)), 3,
                  C_XP_FG)
        self.text(str(level), cx, y + 6, 8, (0.55, 1.0, 0.15, 1.0), True, "center")

    def bubbles(self, ratio, x, y, count=10):
        n = max(0, min(count, int(round(ratio * count))))
        for i in range(n):
            self.rect(x + i * 8, y, 7, 7, (0.75, 0.90, 1.0, 0.85))
            self.rect(x + i * 8 + 2, y + 2, 3, 3, (1.0, 1.0, 1.0, 0.95))

    def tooltip(self, lines, x, y):
        if not lines:
            return
        w = max(self.text_width(t, 8) for t in lines) + 8
        h = 10 * len(lines) + 6
        self.rect(x, y - h, w, h, C_TOOLTIP_BG)
        self.outline(x, y - h, w, h, 1.0, C_TOOLTIP_BD)
        for i, t in enumerate(lines):
            self.text(t, x + 4, y - h + 4 + (len(lines) - 1 - i) * 10, 8, C_TEXT, True)

    def panel(self, x, y, w, h, bg=C_INV_PANEL):
        self.rect(x, y, w, h, bg)
        self.outline(x, y, w, h, 1.0, C_INV_BORDER)

    def button(self, label, x, y, w, h, hover=False, size=9):
        self.rect(x, y, w, h, C_BTN_HOVER if hover else C_BTN)
        self.outline(x, y, w, h, 1.0, C_BTN_BORDER)
        self.text(label, x + w / 2, y + h / 2 - size * 0.5 + 1, size, C_TEXT, True, "center")

    def inv_slot(self, x, y, size, hover=False, dark=False):
        self.rect(x, y, size, size, (0.42, 0.42, 0.42, 1.0) if not dark
                  else (0.30, 0.30, 0.30, 1.0))
        self.rect(x, y, size, 1, (0.25, 0.25, 0.25, 1.0))
        self.rect(x, y, 1, size, (0.25, 0.25, 0.25, 1.0))
        self.rect(x, y + size - 1, size, 1, (0.98, 0.98, 0.98, 1.0))
        self.rect(x + size - 1, y, 1, size, (0.98, 0.98, 0.98, 1.0))
        if hover:
            self.rect(x + 1, y + 1, size - 2, size - 2, (1.0, 1.0, 1.0, 0.45))

    def dim(self, alpha=0.62):
        self.rect(0, 0, self.w, self.h, (0, 0, 0, alpha))

    def crack_overlay(self, tile, x0, y0, x1, y1, alpha=0.85):
        self.icon_px(tile, x0, y0, x1, y1, (1, 1, 1, alpha))

    def icon_px(self, tile, x0, y0, x1, y1, tint=(1.0, 1.0, 1.0, 1.0)):
        s = self.scale
        self.icon(tile, x0 / s, y0 / s, (x1 - x0) / s, (y1 - y0) / s, tint)


# ---------------------------------------------------------------------------
# 布局（绘制与点击共用）
# ---------------------------------------------------------------------------
def hotbar_layout(cx, bottom=3.0):
    slot = 20.0
    total_w = 9 * slot + 2
    return cx - total_w / 2.0, bottom, slot, total_w


def inventory_rows(creative):
    return 5 if creative else 3


def inventory_layout(cx, cy, creative=False):
    slot = 20.0
    rows = inventory_rows(creative)
    grid_w = 9 * slot + 2
    grid_h = rows * slot + 2
    panel_w = grid_w + 16
    panel_h = 14 + grid_h + 8 + (slot + 2) + 8
    px = cx - panel_w / 2.0
    py = cy - panel_h / 2.0
    return {
        "panel": (px, py, panel_w, panel_h),
        "title_y": py + panel_h - 11,
        "grid_origin": (px + 8, py + 8 + (slot + 2) + 8),
        "grid": (px + 8, py + 8 + (slot + 2) + 8, grid_w, grid_h),
        "hotbar_origin": (px + 8, py + 8),
        "hotbar": (px + 8, py + 8, grid_w, slot + 2),
        "slot": slot,
        "rows": rows,
        "creative": creative,
    }


def inventory_slot_rects(lay):
    """返回 [(屏幕矩形, 下标, 种类)]；种类 ∈ hotbar/storage/palette。"""
    out = []
    slot = lay["slot"]
    sx, sy = lay["hotbar_origin"]
    for i in range(9):
        out.append(((sx + i * slot, sy, slot, slot), i, "hotbar"))
    gx, gy = lay["grid_origin"]
    rows = lay["rows"]
    for r in range(rows):
        for c in range(9):
            rect = (gx + c * slot, gy + (rows - 1 - r) * slot, slot, slot)
            idx = 9 + r * 9 + c
            kind = "palette" if lay["creative"] else "storage"
            out.append((rect, idx, kind))
    return out


def pause_layout(cx, cy, render_distance=6):
    w, h = 150.0, 20.0
    labels = [
        ("回到游戏", "resume"),
        ("保存世界", "save"),
        (f"渲染距离: {render_distance}", "render"),
        ("切换游戏模式", "gamemode"),
        ("读取存档", "load"),
        ("退出到 Blender", "quit"),
    ]
    total = len(labels) * (h + 4)
    x = cx - w / 2.0
    y = cy + total / 2.0 - h
    out = []
    for label, action in labels:
        out.append((label, (x, y, w, h), action))
        y -= h + 4
    return out


def death_layout(cx, cy):
    w, h = 150.0, 20.0
    labels = [("重生", "respawn"), ("退出到 Blender", "quit")]
    y = cy - 18 - h
    out = []
    for label, action in labels:
        out.append((label, (cx - w / 2, y, w, h), action))
        y -= h + 4
    return out


def point_in(rect, px, py):
    x, y, w, h = rect
    return x <= px <= x + w and y <= py <= y + h
