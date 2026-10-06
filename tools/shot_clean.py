"""干净的首屏截图：只开游戏、等它稳定，然后截图（不做任何会打断渲染的操作）。

用法：blender --enable-event-simulate --factory-startup --python tools/shot_clean.py -- [小时] [截图]
"""
from __future__ import annotations

import math
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WAIT = float(argv[0]) if argv else 22.0
SHOT = argv[1] if len(argv) > 1 else os.path.join(ROOT, "shot_clean.png")

import blender_minecraft as pkg              # noqa: E402
import blender_minecraft.mc_game as mc_game  # noqa: E402

pkg.register()


def view():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area, next(r for r in area.regions if r.type == "WINDOW")
    return None, None, None


win, area, region = view()
try:
    win.event_simulate(type="LEFTMOUSE", value="PRESS",
                       x=win.width - 8, y=win.height - 8)
    win.event_simulate(type="LEFTMOUSE", value="RELEASE",
                       x=win.width - 8, y=win.height - 8)
except Exception as exc:
    print("关启动画面失败:", exc)

with bpy.context.temp_override(window=win, area=area, region=region,
                               space_data=area.spaces.active):
    bpy.ops.mc_blender.play("INVOKE_DEFAULT", seed=20240501, render_distance=4,
                            creative=True, quality="medium")

STATE = {"t0": time.time()}


def tick():
    game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
    el = time.time() - STATE["t0"]
    if game is not None and "posed" not in STATE and el > WAIT * 0.5:
        STATE["posed"] = True
        game.player.pitch = -0.12
        game.player.yaw = 0.45
        print(f"[SHOT] 模式={game.mode} FPS={game.fps:.1f} "
              f"区块={len(game.world.chunks)}")
    if el > WAIT:
        if game is not None:
            game.player.pitch = -0.12
            game.player.yaw = 0.45
            game._item_name_timer = 0.0
            game.chat.clear()
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.screen.screenshot_area(filepath=SHOT)
            print(f"[SHOT] 已保存 {SHOT} "
                  f"({os.path.getsize(SHOT)/1024:.0f} KB) "
                  f"FPS={getattr(game, 'fps', 0):.1f}")
        except Exception as exc:
            print("[SHOT] 失败:", exc)
        if game is not None:
            game._shutdown(bpy.context)
        bpy.ops.wm.quit_blender()
        return None
    return 0.25


bpy.app.timers.register(tick, first_interval=0.5, persistent=True)
