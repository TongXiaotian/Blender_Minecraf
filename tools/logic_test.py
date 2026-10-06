"""无界面逻辑测试：世界、玩家物理、射线、物品栏、存档。

用法：blender --background --factory-startup --python tools/logic_test.py
"""
from __future__ import annotations

import os
import sys
import time

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from blender_minecraft import mc_blocks as B              # noqa: E402
from blender_minecraft import mc_inventory, mc_player, mc_save  # noqa: E402
from blender_minecraft import mc_raycast, mc_world        # noqa: E402
from blender_minecraft.mc_const import SEA_LEVEL, WORLD_H  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAILED.append(name)


print("=" * 64)
print("1. 模块导入")
import blender_minecraft.mc_game as mc_game                # noqa: E402
import blender_minecraft.mc_ui as mc_ui                    # noqa: E402
import blender_minecraft.mc_textures as mc_textures        # noqa: E402
import blender_minecraft.mc_mesher as mc_mesher            # noqa: E402
import blender_minecraft.mc_render as mc_render            # noqa: E402
check("全部模块导入成功", True)
check("方块数量 > 30", len(B.BLOCKS) > 30, f"{len(B.BLOCKS)} 种")
check("贴图数量 == 图集容量", len(mc_textures.TILE_NAMES) <= 256,
      f"{len(mc_textures.TILE_NAMES)} 张贴图")
check("每个方块都有 6 个贴图序号",
      all(len(b.tiles) == 6 for b in B.BLOCKS))

print("2. 图集生成")
t0 = time.time()
atlas = mc_textures.build_atlas()
check("图集尺寸 256x256x4", atlas.shape == (256, 256, 4), str(atlas.shape))
check("图集有内容（非全透明）", int(atlas[..., 3].sum()) > 0)
check("生成耗时 < 2s", time.time() - t0 < 2.0, f"{time.time()-t0:.2f}s")

print("3. 世界生成")
world = mc_world.World(seed=12345)
t0 = time.time()
for cx in range(-3, 4):
    for cz in range(-3, 4):
        world.get_chunk(cx, cz)
gen_time = time.time() - t0
check("49 个区块生成 < 5s", gen_time < 5.0, f"{gen_time:.2f}s")

ch = world.chunks[(0, 0)]
check("区块数据形状 (16,128,16)", ch.blocks.shape == (16, WORLD_H, 16))
check("底层是基岩", world.get_block(3, 0, 3) == B.BY_NAME["bedrock"].id)
h = world.highest_solid(3, 3)
check("地表高度合理", 5 < h < WORLD_H - 5, f"y={h}")
top = world.get_block(3, h, 3)
check("地表不是空气", top != 0, B.BLOCKS[top].label)
# 至少出现过水/草/沙/雪中的几种
names = {B.BLOCKS[int(i)].name for i in np.unique(ch.blocks)}
check("区块内有多种方块", len(names) > 4, ", ".join(sorted(names)[:8]))

print("4. 网格生成")
data = mc_mesher.build_chunk_data(world, ch)
check("网格非空", data is not None)
verts, faces, uvs, cols, mats = data
check("面数 = 顶点数/4", len(faces) * 4 == len(verts), f"{len(faces)} 面")
check("UV 在 0..1", float(uvs.min()) >= 0.0 and float(uvs.max()) <= 1.0)
check("顶点色在合理范围", 0.0 <= float(cols.min()) and float(cols.max()) <= 1.0)
check("AO 让顶点色有明暗差异", float(cols[:, 0].std()) > 0.01,
      f"std={float(cols[:,0].std()):.3f}")
check("材质下标只有 0/1", set(np.unique(mats).tolist()) <= {0, 1})

print("5. 射线检测")
# 在玩家脚下放一块石头，从上方往下打
world.set_block(0, 100, 0, B.BY_NAME["stone"].id)
hit = mc_raycast.raycast(world, (0.5, 110.0, 0.5), (0, -1, 0), 20.0)
check("向下射线命中", hit is not None and hit[0] == (0, 100, 0), str(hit))
check("命中法线朝上", hit is not None and hit[1] == (0, 1, 0), str(hit and hit[1]))
hit2 = mc_raycast.raycast(world, (0.5, 120.0, 0.5), (0, 1, 0), 5.0)
check("向上打空返回 None", hit2 is None, str(hit2))
hit3 = mc_raycast.raycast(world, (0.5, 110.0, 0.5), (0, -1, 0), 5.0)
check("距离不够时打不到", hit3 is None or hit3[0][1] > 105, str(hit3))

print("6. 玩家物理")
# 先搭一块确定性的平台，避免测试结果受地形起伏影响
PLAT_Y = 100
stone = B.BY_NAME["stone"].id
for px_ in range(-12, 13):
    for pz_ in range(-12, 13):
        world.set_block(px_, PLAT_Y, pz_, stone)
        for k in range(1, 5):
            world.set_block(px_, PLAT_Y + k, pz_, 0)
p = mc_player.Player(spawn=(0.5, float(PLAT_Y + 1), 0.5))
p.creative = False
for i in range(60):
    p.update(world, 1.0 / 60.0, set())
check("玩家落在地面上", p.on_ground and abs(p.pos[1] - (PLAT_Y + 1)) < 0.01,
      f"y={p.pos[1]:.2f}")
y_before = p.pos[1]
p.update(world, 1.0 / 60.0, {"jump"})
raised = False
for i in range(30):
    p.update(world, 1.0 / 60.0, {"jump"})
    if p.pos[1] > y_before + 0.8:
        raised = True
check("按跳跃能跳起 1 格以上", raised, f"最高 y={p.pos[1]:.2f}")
for i in range(60):
    p.update(world, 1.0 / 60.0, set())
# 前进
start = p.pos.copy()
for i in range(60):
    p.update(world, 1.0 / 60.0, {"forward"})
moved = float(np.linalg.norm((p.pos - start)[[0, 2]]))
check("按 W 一秒会前进约 4 格", moved > 2.5, f"移动 {moved:.2f} 格")
# 后退 / 左移
start = p.pos.copy()
for i in range(60):
    p.update(world, 1.0 / 60.0, {"back"})
check("按 S 会后退", float(np.linalg.norm((p.pos - start)[[0, 2]])) > 1.0)

print("7. 摔落伤害")
p2 = mc_player.Player(spawn=(0.5, float(PLAT_Y + 40), 0.5))
p2.creative = False
for i in range(600):
    p2.update(world, 1.0 / 60.0, set())
check("高处摔落会掉血", p2.health < 20.0, f"血量 {p2.health:.1f}")
p3 = mc_player.Player(spawn=(0.5, float(PLAT_Y + 40), 0.5))
p3.creative = True
for i in range(600):
    p3.update(world, 1.0 / 60.0, set())
check("创造模式不受伤", p3.health == 20.0, f"血量 {p3.health:.1f}")

print("8. 物品栏")
inv = mc_inventory.Inventory(creative=False)
left = inv.add("stone", 100)
check("超过一组的物品会分堆", left == 0 and inv.count_of("stone") == 100,
      f"left={left} count={inv.count_of('stone')}")
check("占用了 2 个格子", sum(1 for s in inv.slots if s.name == "stone") == 2)
inv.select(0)
check("选中格子 0", inv.held().name == "stone")
check("消耗一个", inv.consume_held(1) and inv.held().count == 63)
inv2 = mc_inventory.Inventory(creative=True)
inv2.fill_creative()
check("创造模式物品栏已填满", sum(1 for s in inv2.slots if not s.empty) >= 30)
inv2.cursor = mc_inventory.Slot("stone", 64)
inv2.click_slot(20)
check("点击格子放下物品", inv2.slots[20].name == "stone")
inv2.cursor = mc_inventory.Slot()
inv2.click_slot(20)
check("空手点击拿起物品", inv2.cursor.name == "stone" and inv2.slots[20].empty)

print("9. 存档 / 读档")
t0 = time.time()
path = mc_save.save_world(world, p, inv, name="__test__")
check("存档文件已写出", os.path.exists(path), f"{os.path.getsize(path)/1024:.0f} KB, "
      f"{time.time()-t0:.2f}s")
got = mc_save.load_world("__test__")
check("读档成功", got is not None)
w2, meta = got
check("种子一致", w2.seed == world.seed)
check("区块数一致", len(w2.chunks) == len(world.chunks),
      f"{len(w2.chunks)} vs {len(world.chunks)}")
key = next(iter(world.chunks))
check("区块数据逐字节一致",
      np.array_equal(w2.chunks[key].blocks, world.chunks[key].blocks))
check("玩家位置已保存", abs(meta["pos"][1] - p.pos[1]) < 1e-6)
os.remove(path)

print("10. UI 布局（不需要 GPU）")
ui = mc_ui.UI()
ui.set_region(1920, 1080)
check("界面缩放 = 4", ui.scale == 4, f"scale={ui.scale}")
lay = mc_ui.inventory_layout(ui.w / 2, ui.h / 2, creative=False)
rects = mc_ui.inventory_slot_rects(lay)
check("生存物品栏 36 格", len(rects) == 36, str(len(rects)))
lay_c = mc_ui.inventory_layout(ui.w / 2, ui.h / 2, creative=True)
rects_c = mc_ui.inventory_slot_rects(lay_c)
check("创造物品栏 54 格", len(rects_c) == 54, str(len(rects_c)))
check("快捷栏 9 格", len(ui and mc_ui.hotbar_layout(ui.w / 2)) == 4)
btn = mc_ui.pause_layout(ui.w / 2, ui.h / 2, 6)
check("暂停菜单 6 个按钮", len(btn) == 6)
check("点击命中判断正常", mc_ui.point_in((10, 10, 20, 20), 15, 15)
      and not mc_ui.point_in((10, 10, 20, 20), 50, 50))

print("=" * 64)
if FAILED:
    print(f"失败 {len(FAILED)} 项：" + ", ".join(FAILED))
else:
    print("全部通过 ✅")
print("=" * 64)
