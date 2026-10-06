"""性能对照实验：分离"渲染开销"和"逻辑开销"。

用法：blender --factory-startup --python tools/perf_test.py -- [输出json]
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
OUT = argv[0] if argv else os.path.join(ROOT, "build", "perf.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def view():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            region = next((r for r in area.regions if r.type == "WINDOW"), None)
            return win, area, region
    return None, None, None


def send(etype, value, dx=0, dy=0):
    game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
    win, area, region = view()
    if game is None or region is None:
        return
    game.handle_test_event({
        "type": etype, "value": value,
        "mouse_x": region.x + region.width // 2 + dx,
        "mouse_y": region.y + region.height // 2 + dy,
    })


class Perf:
    """每个配置跑 2 秒，测真实 tick 频率、每段耗时、强制重绘时间。"""
    # (名称, shading, 阴影, HUD, 冻结, 禁流式, eevee覆盖)
    CONFIGS = [
        ("运行 默认(MATERIAL+阴影+流式)", "MATERIAL", True, True, False, False, {}),
        ("运行 关raytracing", "MATERIAL", True, True, False, True, {"use_raytracing": False}),
        ("运行 关raytracing+fastgi", "MATERIAL", True, True, False, True,
         {"use_raytracing": False, "use_fast_gi": False}),
        ("运行 关raytracing+fastgi+阴影", "MATERIAL", True, True, False, True,
         {"use_raytracing": False, "use_fast_gi": False, "use_shadows": False}),
        ("运行 SOLID+TEXTURE 关raytracing", "SOLID", True, True, False, True,
         {"use_raytracing": False}),
        ("运行 默认设置+关流式", "MATERIAL", True, True, False, True, {}),
    ]

    def __init__(self):
        self.t0 = time.time()
        self.idx = -1
        self.phase_start = 0.0
        self.results = []
        self.last_ticks = 0
        self.ready = False
        self.game = None
        self.stage = 0
        self.perf0 = {}

    def apply(self, stype, shadows, hud, eevee):
        win, area, region = view()
        sh = area.spaces.active.shading
        sh.type = stype
        sh.color_type = "TEXTURE" if stype == "SOLID" else "MATERIAL"
        sh.show_shadows = shadows
        ee = bpy.context.scene.eevee
        # 先恢复默认，再应用覆盖
        defaults = {"use_raytracing": True, "use_fast_gi": True, "use_shadows": True}
        defaults.update(eevee)
        for key, val in defaults.items():
            try:
                setattr(ee, key, val)
            except Exception as exc:
                print("[PERF] eevee 设置失败", key, exc)
        game = self.game
        if hud and game._hud_handle is None:
            game._hud_handle = bpy.types.SpaceView3D.draw_handler_add(
                game._draw_hud, (), "WINDOW", "POST_PIXEL")
        elif not hud and game._hud_handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(game._hud_handle, "WINDOW")
            except Exception:
                pass
            game._hud_handle = None

    def tick(self):
        self.game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        game = self.game
        if game is None:
            bpy.ops.wm.quit_blender()
            return None
        now = time.time()
        if not self.ready:
            if game.mode == "playing" or now - self.t0 > 40:
                self.ready = True
                print(f"[PERF] 载入完成 {now - self.t0:.1f}s 区块 {len(game.world.chunks)}")
                self.next_config()
            return 0.05

        name, stype, shadows, hud, frozen, no_stream, eevee = self.CONFIGS[self.idx]
        if self.stage == 0 and now - self.phase_start > 2.0:
            ticks = game.perf["ticks"]
            span = now - self.phase_start
            self.phase_ticks = round((ticks - self.last_ticks) / span, 2)
            n = max(1, ticks - self.last_ticks)
            detail = {k[2:]: round((v - self.perf0.get(k, 0.0)) / n * 1000, 1)
                      for k, v in game.perf.items() if k.startswith("t_")}
            detail["per_tick_ms"] = round(span / n * 1000, 1)
            self.stage = 1
            self.phase_start = now
            # 强制重绘 10 次，测单帧渲染耗时
            win, area, region = view()
            try:
                t0 = time.perf_counter()
                with bpy.context.temp_override(window=win, area=area, region=region):
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=10)
                self.redraw_ms = round((time.perf_counter() - t0) / 10 * 1000, 1)
            except Exception as exc:
                self.redraw_ms = f"失败 {type(exc).__name__}"
            self.results.append({
                "config": name, "ticks_per_sec": self.phase_ticks,
                "redraw_ms": self.redraw_ms, "chunks": len(game.world.chunks),
                "fps_reported": round(float(game.fps), 1),
                "ms": detail,
            })
            print("[PERF]", self.results[-1])
            if not self.next_config():
                self.finish()
                return None
        return 0.05

    def next_config(self):
        self.idx += 1
        if self.idx >= len(self.CONFIGS):
            return False
        name, stype, shadows, hud, frozen = self.CONFIGS[self.idx]
        self.apply(stype, shadows, hud)
        game = self.game
        game.frozen = frozen
        game.perf["ticks"] = 0
        self.perf0 = {k: v for k, v in game.perf.items() if k.startswith("t_")}
        self.last_ticks = 0
        self.stage = 0
        self.phase_start = time.time()
        print(f"[PERF] 测试配置：{name}")
        return True

    def finish(self):
        game = self.game
        game.frozen = False
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({
                "blender": bpy.app.version_string,
                "results": self.results,
                "perf": {k: round(v, 3) for k, v in game.perf.items()},
                "draw_errors": mc_game.DRAW_ERRORS[:6],
                "tick_errors": mc_game.TICK_ERRORS[:6],
            }, fh, ensure_ascii=False, indent=2)
        print("[PERF] 写入", OUT)
        bpy.ops.wm.quit_blender()


pkg.register()
win, area, region = view()
with bpy.context.temp_override(window=win, area=area, region=region,
                               space_data=area.spaces.active):
    bpy.ops.mc_blender.play("INVOKE_DEFAULT", seed=20240501, render_distance=4,
                            creative=True)
bpy.app.timers.register(Perf().tick, first_interval=0.2, persistent=True)
