"""方块注册表：id、名字、六个面的贴图、硬度、是否固体/透明等。

面顺序固定为 (PX, NX, PY, NY, PZ, NZ)，与 mc_const 中的 FACE_* 常量一致。
"""
from __future__ import annotations

from .mc_const import FACES, FACE_NX, FACE_NY, FACE_PX, FACE_PY, FACE_PZ, FACE_NZ
from .mc_textures import TILE_INDEX


class Block:
    __slots__ = ("id", "name", "label", "tiles", "solid", "opaque", "liquid",
                 "hardness", "light", "tool", "drop", "drop_count", "unbreakable",
                 "sound", "flammable")

    def __init__(self, id, name, label, tiles, *, solid=True, opaque=True, liquid=False,
                 hardness=1.5, light=0, tool="pickaxe", drop=None, drop_count=1,
                 unbreakable=False, sound="stone", flammable=False):
        self.id = id
        self.name = name
        self.label = label
        self.tiles = tiles                  # 长度 6 的贴图序号元组
        self.solid = solid                  # 是否阻挡玩家
        self.opaque = opaque                # 是否遮住相邻面（用于面剔除）
        self.liquid = liquid
        self.hardness = hardness            # 挖掘时间基数，-1 表示不可破坏
        self.light = light                  # 自发光（目前仅用于 UI 提示）
        self.tool = tool
        self.drop = drop if drop is not None else name
        self.drop_count = drop_count
        self.unbreakable = unbreakable
        self.sound = sound
        self.flammable = flammable

    def tile(self, face: int) -> int:
        return self.tiles[face]


BLOCKS: list[Block] = []


def _six(all_=None, top=None, bottom=None, side=None, north=None, south=None):
    """构造 6 面贴图序号元组；未指定的面自动回退到其它已给的贴图。"""
    if side is None:
        side = all_ if all_ is not None else (top if top is not None else bottom)
    if top is None:
        top = all_ if all_ is not None else side
    if bottom is None:
        bottom = all_ if all_ is not None else side
    if all_ is None and side is None:
        raise ValueError("至少要给出一个贴图名")
    n = north if north is not None else side
    so = south if south is not None else side
    names = (side, side, top, bottom, so, n)
    return tuple(TILE_INDEX[x] for x in names)


def _add(name, label, tiles, **kw) -> Block:
    blk = Block(len(BLOCKS), name, label, tiles, **kw)
    BLOCKS.append(blk)
    return blk


# --------------------------------------------------------------------------
# 注册所有方块（0 号必须是空气）
# --------------------------------------------------------------------------
_add("air", "空气", (0,) * 6, solid=False, opaque=False, hardness=0, unbreakable=True)
_add("stone", "石头", _six("stone"), hardness=1.5)
_add("grass_block", "草方块", _six(top="grass_top", bottom="dirt", side="grass_side"),
     hardness=0.6, tool="shovel", drop="dirt", sound="grass")
_add("dirt", "泥土", _six("dirt"), hardness=0.5, tool="shovel", sound="dirt")
_add("cobblestone", "圆石", _six("cobblestone"), hardness=2.0)
_add("oak_planks", "橡木木板", _six("oak_planks"), hardness=2.0, tool="axe",
     sound="wood", flammable=True)
_add("bedrock", "基岩", _six("bedrock"), hardness=-1, unbreakable=True)
_add("sand", "沙子", _six("sand"), hardness=0.5, tool="shovel", sound="sand")
_add("gravel", "沙砾", _six("gravel"), hardness=0.6, tool="shovel", sound="sand")
_add("oak_log", "橡木原木", _six(top="oak_log_top", bottom="oak_log_top",
                                 side="oak_log_side"), hardness=2.0, tool="axe",
     sound="wood", flammable=True)
_add("oak_leaves", "橡树树叶", _six("oak_leaves"), hardness=0.2, tool="shears",
     sound="grass", flammable=True)
_add("water", "水", _six("water"), solid=False, opaque=False, liquid=True,
     hardness=-1, unbreakable=True, tool="none", sound="water")
_add("glass", "玻璃", _six("glass"), opaque=False, hardness=0.3, tool="none",
     drop="glass", sound="glass")
_add("coal_ore", "煤矿石", _six("coal_ore"), hardness=3.0)
_add("iron_ore", "铁矿石", _six("iron_ore"), hardness=3.0)
_add("gold_ore", "金矿石", _six("gold_ore"), hardness=3.0)
_add("diamond_ore", "钻石矿石", _six("diamond_ore"), hardness=3.0)
_add("bricks", "砖块", _six("bricks"), hardness=2.0)
_add("snow_block", "雪块", _six("snow"), hardness=0.2, tool="shovel", sound="snow")
_add("ice", "冰", _six("ice"), opaque=False, hardness=0.5, tool="pickaxe", sound="glass")
_add("sandstone", "砂岩", _six("sandstone"), hardness=0.8)
_add("obsidian", "黑曜石", _six("obsidian"), hardness=50.0, unbreakable=False)
_add("glowstone", "荧石", _six("glowstone"), hardness=0.3, light=15, sound="glass")
_add("crafting_table", "工作台", _six(top="crafting_table_top", side="crafting_table_side"),
     hardness=2.5, tool="axe", sound="wood", flammable=True)
_add("furnace", "熔炉", _six(top="furnace_top", bottom="furnace_top", side="furnace_side"),
     hardness=3.5)
_add("tnt", "TNT", _six(top="tnt_top", bottom="tnt_top", side="tnt_side"),
     hardness=0.0, tool="none", sound="grass")
_add("iron_block", "铁块", _six("iron_block"), hardness=5.0)
_add("gold_block", "金块", _six("gold_block"), hardness=3.0)
_add("diamond_block", "钻石块", _six("diamond_block"), hardness=5.0)
_add("bookshelf", "书架", _six("bookshelf"), hardness=1.5, tool="axe", sound="wood",
     flammable=True)
_add("netherrack", "下界岩", _six("netherrack"), hardness=0.4)
_add("stone_bricks", "石砖", _six("stone_bricks"), hardness=1.5)
_add("snow_layer", "雪", _six("snow"), hardness=0.1, tool="shovel", sound="snow")
# 额外几种常用方块（借用已有贴图，丰富创造模式物品栏）
_add("dirt_path", "土径", _six(top="dirt", bottom="dirt", side="dirt"), hardness=0.6,
     tool="shovel", sound="dirt")
_add("mossy_cobblestone", "苔石", _six("cobblestone"), hardness=2.0)
_add("oak_planks_dark", "深色木板", _six("oak_planks"), hardness=2.0, tool="axe")

# 名字 -> 方块
BY_NAME = {b.name: b for b in BLOCKS}
# 中文名 -> 方块
BY_LABEL = {b.label: b for b in BLOCKS}

AIR = BLOCKS[0]

# 面剔除用的查找表（numpy 索引用）
import numpy as np  # noqa: E402

OPAQUE_TABLE = np.array([b.opaque for b in BLOCKS], dtype=bool)
SOLID_TABLE = np.array([b.solid for b in BLOCKS], dtype=bool)
LIQUID_TABLE = np.array([b.liquid for b in BLOCKS], dtype=bool)
HARDNESS_TABLE = np.array([max(b.hardness, 0.0) for b in BLOCKS], dtype=np.float32)
LIGHT_TABLE = np.array([b.light for b in BLOCKS], dtype=np.uint8)
# 每个方块的 6 面贴图序号，形状 (方块数, 6)
TILE_TABLE = np.array([b.tiles for b in BLOCKS], dtype=np.int32)

# 创造模式物品栏顺序（原版风格的分类顺序）
CREATIVE_ITEMS = [
    "stone", "cobblestone", "stone_bricks", "bricks", "sandstone", "obsidian",
    "dirt", "grass_block", "sand", "gravel", "snow_block", "snow_layer",
    "oak_planks", "oak_log", "oak_leaves", "bookshelf", "crafting_table", "furnace",
    "glass", "glowstone", "tnt",
    "coal_ore", "iron_ore", "gold_ore", "diamond_ore",
    "iron_block", "gold_block", "diamond_block", "bedrock",
    "water", "ice", "netherrack", "mossy_cobblestone", "dirt_path", "oak_planks_dark",
]

# 生存模式默认给的物品（前 9 格 = 快捷栏）
SURVIVAL_START = []


def get(name_or_id):
    if isinstance(name_or_id, int):
        return BLOCKS[name_or_id]
    return BY_NAME[name_or_id]
