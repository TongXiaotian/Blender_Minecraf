"""用户主路径测试：启用的插件 + 侧栏按钮（mc_blender.play_panel）启动游戏 + 截图。

用法（需要先安装过 zip）：
    set BLENDER_USER_SCRIPTS=<目录>
    set BLENDER_USER_CONFIG=<目录>
    blender --enable-event-simulate --python tools/panel_test.py -- [截图路径]
"""
from __future__ import annotations

import json
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SHOT = argv[0] if argv else os.path.join(ROOT, "shot_panel.png")
OUT = os.path.join(ROOT, "build", "panel_result.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

STEPS = []


def log(msg):
    print("[PANEL]", msg, flush=True)
    STEPS.append(str(msg))


def view():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area, next((r for r in area.regions if r.type == "WINDOW"), None)
    return None, None, None


def sim(etype, value="PRESS", dx=0):
    win, area, region = view()
    if region is None:
        return
    try:
        win.event_simulate(type=etype, value=value,
                           x=region.x + region.width // 2 + dx,
                           y=region.y + region.height // 2)
    except Exception as exc:
        log(f"事件失败 {etype}: {exc}")


# 1. 按用户流程启用插件
try:
    bpy.ops.preferences.addon_enable(module="blender_minecraft")
    log("插件已启用（addon_enable）")
except Exception as exc:
    log(f"启用失败: {exc}")

import blender_minecraft.mc_game as mc_game  # noqa: E402

# 2. 关掉启动画面
sim("LEFTMOUSE", "PRESS", dx=700)
sim("LEFTMOUSE", "RELEASE", dx=700)

# 3. 用侧栏按钮启动（先改一下设置，验证属性确实生效）
scene = bpy.context.scene
scene.mc_settings.seed = 20240501
scene.mc_settings.render_distance = 4
scene.mc_settings.quality = "medium"
scene.mc_settings.creative = True

win, area, region = view()
with bpy.context.temp_override(window=win, area=area, region=region,
                               space_data=area.spaces.active):
    bpy.ops.mc_blender.play_panel()

game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
log(f"面板按钮启动：实例={game is not None} 种子={getattr(game, 'seed', None)} "
    f"渲染距离={getattr(game, '_rd', None)} 画质={getattr(game, 'quality', None)}")

RESULT = {"steps": STEPS}


class Runner:
    def __init__(self):
        self.t0 = time.time()
        self.done = False

    def tick(self):
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        el = time.time() - self.t0
        if game is not None and game.mode != "loading" and not self.done:
            self.done = True
            log(f"进入游戏：模式={game.mode} 区块={len(game.world.chunks)} "
                f"画质={game.quality} 阴影={area.spaces.active.shading.show_shadows}")
            RESULT["quality_applied"] = {
                "shadows": bool(area.spaces.active.shading.show_shadows),
                "taa_samples": int(scene.eevee.taa_samples),
                "view_transform": scene.view_settings.view_transform,
            }
            sim("LEFTMOUSE", "PRESS")
            sim("LEFTMOUSE", "RELEASE")
            sim("F3", "PRESS")
            sim("F3", "RELEASE")
        if el > 16.0 and not RESULT.get("obj_probe"):
            RESULT["obj_probe"] = {}
            objs = [o for o in bpy.data.objects
                    if o.name.startswith("MC_chunk_") and not o.hide_viewport]

            def time_render():
                t0 = time.perf_counter()
                try:
                    with bpy.context.temp_override(window=win, area=area, region=region):
                        bpy.ops.render.opengl(write_still=False, view_context=True)
                except Exception:
                    pass
                return round(time.perf_counter() - t0, 2)

            RESULT["obj_probe"]["all"] = [len(objs), time_render()]
            hidden = []
            for o in objs[9:]:
                o.hide_viewport = True
                hidden.append(o)
            RESULT["obj_probe"]["9_objs"] = [9, time_render()]
            for o in objs[4:9]:
                o.hide_viewport = True
                hidden.append(o)
            RESULT["obj_probe"]["4_objs"] = [4, time_render()]
            for o in hidden:
                o.hide_viewport = False
            log("对象数/渲染耗时：" + json.dumps(RESULT["obj_probe"], ensure_ascii=False))
        if el > 10.0 and not RESULT.get("gl_probe"):
            RESULT["gl_probe"] = True
            t0 = time.perf_counter()
            try:
                scene.render.filepath = SHOT.replace(".png", "_gl.png")
                scene.render.image_settings.file_format = "PNG"
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.render.opengl(write_still=True, view_context=True)
                log(f"OpenGL 渲染截图: {SHOT.replace('.png', '_gl.png')} "
                    f"耗时 {time.perf_counter()-t0:.1f}s")
            except Exception as exc:
                log(f"OpenGL 渲染失败: {type(exc).__name__}: {exc}")
        if el > 8.0 and not RESULT.get("solid_probe"):
            RESULT["solid_probe"] = True
            sh = area.spaces.active.shading
            before = sh.type
            sh.type = "SOLID"
            sh.color_type = "TEXTURE"
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=SHOT.replace(".png", "_solid.png"))
                log(f"SOLID 模式截图: {SHOT.replace('.png', '_solid.png')}")
            except Exception as exc:
                log(f"SOLID 截图失败: {exc}")
            sh.type = before
            sh.color_type = "MATERIAL"
        if el > 6.0 and not RESULT.get("shot0"):
            RESULT["shot0"] = True
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=SHOT.replace(".png", "_warm.png"))
                log(f"截图0（准备阶段）: {SHOT.replace('.png', '_warm.png')} "
                    f"模式={getattr(game, 'mode', None)}")
            except Exception as exc:
                log(f"截图失败: {exc}")
        if el > 14.0 and not RESULT.get("shot1"):
            RESULT["shot1"] = True
            game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
            if game is not None:
                game.player.pitch = -0.20
                game.player.yaw = 0.6
                game._item_name_timer = 0.0
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=SHOT)
                log(f"截图1: {SHOT}")
            except Exception as exc:
                log(f"截图失败: {exc}")
        if el > 20.0:
            try:
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.screen.screenshot_area(filepath=SHOT.replace(".png", "_late.png"))
                log(f"截图2: {SHOT.replace('.png', '_late.png')}")
            except Exception as exc:
                log(f"截图失败: {exc}")
            RESULT.update({
                "mode": getattr(game, "mode", None),
                "fps": round(float(getattr(game, "fps", 0.0)), 1),
                "chunks": len(game.world.chunks) if game else 0,
                "draw_errors": mc_game.DRAW_ERRORS[:5],
                "tick_errors": mc_game.TICK_ERRORS[:5],
            })
            objs = [o for o in bpy.data.objects if o.name.startswith("MC_chunk_")]
            cam = bpy.data.objects.get("MC_Camera")
            RESULT["viewport"] = {
                "chunk_objects": len(objs),
                "visible": sum(1 for o in objs if not o.hide_viewport),
                "faces_visible": sum(len(o.data.polygons) for o in objs
                                     if not o.hide_viewport),
                "cam_loc": [round(v, 2) for v in cam.location] if cam else None,
                "player": [round(float(v), 2) for v in game.player.pos] if game else None,
                "shading_type": area.spaces.active.shading.type,
            }
            log("视口诊断：" + json.dumps(RESULT["viewport"], ensure_ascii=False))
            if game:
                try:
                    game._shutdown(bpy.context)
                    log("已退出游戏")
                except Exception as exc:
                    log(f"退出异常: {exc}")
            # 退出后确认视图状态还原
            RESULT["after_exit"] = {
                "perspective": area.spaces.active.region_3d.view_perspective,
                "shading": area.spaces.active.shading.type,
                "taa_samples": int(scene.eevee.taa_samples),
                "view_transform": scene.view_settings.view_transform,
                "objects": len(bpy.data.objects),
            }
            log("退出后：" + json.dumps(RESULT["after_exit"], ensure_ascii=False))
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(RESULT, fh, ensure_ascii=False, indent=2)
            log("完成")
            bpy.ops.wm.quit_blender()
            return None
        return 0.2


bpy.app.timers.register(Runner().tick, first_interval=0.3, persistent=True)
