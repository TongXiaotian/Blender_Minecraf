"""退出路径测试：开始游戏 → 玩一会 → 走"退出到 Blender" → 确认 Blender 还活着。

用法：blender --factory-startup --python tools/exit_test.py -- [截图路径]
"""
from __future__ import annotations

import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import blender_minecraft as pkg              # noqa: E402
import blender_minecraft.mc_game as mc_game  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SHOT = argv[0] if argv else os.path.join(ROOT, "shot_after_exit.png")
OUT = os.path.join(ROOT, "build", "exit_result.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

STEPS = []


def log(msg):
    print("[EXIT-TEST]", msg, flush=True)
    STEPS.append(str(msg))


def view():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area, next(r for r in area.regions if r.type == "WINDOW")
    return None, None, None


class Runner:
    def __init__(self):
        self.t0 = time.time()
        self.stage = 0
        self.info = {}

    def tick(self):
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        el = time.time() - self.t0
        if self.stage == 0 and el > 6.0:
            self.stage = 1
            if game is None:
                log("没有活动实例，测试失败")
                return self.finish()
            log(f"退出前：模式={game.mode} 区块={len(game.world.chunks)} "
                f"对象={len(bpy.data.objects)}")
            self.info["before"] = {
                "mode": game.mode, "chunks": len(game.world.chunks),
                "objects": len(bpy.data.objects),
                "collections": [c.name for c in bpy.data.collections],
            }
            win, area, region = view()
            sp = area.spaces.active
            self.info["view_before_exit"] = {
                "perspective": sp.region_3d.view_perspective,
                "shading": sp.shading.type,
                "overlays": sp.overlay.show_overlays,
                "camera": getattr(sp.camera, "name", None),
            }
            try:
                game._shutdown(bpy.context)
                log("已调用退出")
            except Exception as exc:
                log(f"退出时异常: {type(exc).__name__}: {exc}")
        elif self.stage == 1 and el > 8.0:
            self.stage = 2
            self.info["after"] = {
                "objects": len(bpy.data.objects),
                "collections": [c.name for c in bpy.data.collections],
                "mc_images": [i.name for i in bpy.data.images if i.name.startswith("MC_")],
                "mc_materials": [m.name for m in bpy.data.materials
                                 if m.name.startswith("MC_")],
                "mc_meshes": len([m for m in bpy.data.meshes
                                  if m.name.startswith("MC_")]),
            }
            win, area, region = view()
            sp = area.spaces.active
            self.info["view_after_exit"] = {
                "perspective": sp.region_3d.view_perspective,
                "shading": sp.shading.type,
                "overlays": sp.overlay.show_overlays,
                "camera": getattr(sp.camera, "name", None),
            }
            log("退出后：" + json.dumps(self.info["after"], ensure_ascii=False))
            log("视图恢复情况：" + json.dumps(self.info["view_after_exit"],
                                         ensure_ascii=False))
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=SHOT)
                log(f"截图 {SHOT}")
            except Exception as exc:
                log(f"截图失败 {type(exc).__name__}: {exc}")
        elif self.stage == 2 and el > 9.5:
            self.stage = 3
            log("Blender 仍然存活 ✅ 测试通过")
            return self.finish()
        return 0.2

    def finish(self):
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({"steps": STEPS, "info": self.info,
                       "draw_errors": mc_game.DRAW_ERRORS[:5],
                       "tick_errors": mc_game.TICK_ERRORS[:5]},
                      fh, ensure_ascii=False, indent=2)
        bpy.ops.wm.quit_blender()
        return None


pkg.register()
log("插件已注册")
win, area, region = view()
with bpy.context.temp_override(window=win, area=area, region=region,
                               space_data=area.spaces.active):
    bpy.ops.mc_blender.play("INVOKE_DEFAULT", seed=20240501, render_distance=3,
                            creative=True)
bpy.app.timers.register(Runner().tick, first_interval=0.3, persistent=True)
