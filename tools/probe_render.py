"""渲染设置对帧率的影响（全部冻结逻辑，只测绘制）。

用法：blender --factory-startup --python tools/probe_render.py
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

OUT = os.path.join(ROOT, "build", "probe_render.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

PHASES = [
    ("taa=1 阴影ON 默认GI", "MATERIAL", True, {"taa_samples": 1}),
    ("taa=1 阴影OFF 默认GI", "MATERIAL", False, {"taa_samples": 1}),
    ("taa=1 阴影ON 关raytracing+fastgi", "MATERIAL", True,
     {"taa_samples": 1, "use_raytracing": False, "use_fast_gi": False}),
    ("taa=4 阴影ON 默认GI", "MATERIAL", True, {"taa_samples": 4}),
    ("taa=2 阴影ON 关fastgi", "MATERIAL", True, {"taa_samples": 2, "use_fast_gi": False}),
]


def view():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area, next(r for r in area.regions if r.type == "WINDOW")
    return None, None, None


class Probe:
    def __init__(self):
        self.t0 = time.time()
        self.ready = False
        self.idx = -1
        self.t_start = 0.0
        self.t0_ticks = 0
        self.results = []

    def tick(self):
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        if game is None:
            bpy.ops.wm.quit_blender()
            return None
        now = time.time()
        if not self.ready:
            if game.mode == "playing" or now - self.t0 > 40:
                self.ready = True
                game.frozen = True
                game.no_stream = True
                print(f"[R] 载入完成 {now-self.t0:.1f}s 区块 {len(game.world.chunks)}")
                self.next()
            return 0.05
        if now - self.t_start > 2.0:
            n = game.perf["ticks"] - self.t0_ticks
            span = now - self.t_start
            self.results.append({
                "phase": PHASES[self.idx][0],
                "ticks_per_sec": round(n / span, 1),
                "frame_ms": round(span / max(1, n) * 1000, 1),
            })
            print("[R]", self.results[-1])
            if not self.next():
                self.finish()
                return None
        return 0.05

    def next(self):
        self.idx += 1
        if self.idx >= len(PHASES):
            return False
        name, stype, shadows, eevee = PHASES[self.idx]
        win, area, region = view()
        sh = area.spaces.active.shading
        sh.type = stype
        sh.color_type = "TEXTURE" if stype == "SOLID" else "MATERIAL"
        sh.show_shadows = shadows
        ee = bpy.context.scene.eevee
        ee.use_raytracing = True
        ee.use_fast_gi = True
        ee.taa_samples = 16
        for k, v in eevee.items():
            try:
                setattr(ee, k, v)
            except Exception as exc:
                print("[R] 设置失败", k, exc)
        game = mc_game._ACTIVE_INSTANCE[0]
        game.perf["ticks"] = 0
        self.t0_ticks = 0
        self.t_start = time.time()
        print(f"[R] 阶段 {name}")
        return True

    def finish(self):
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({"results": self.results}, fh, ensure_ascii=False, indent=2)
        print("[R] 写入", OUT)
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        if game is not None:
            try:
                game._shutdown(bpy.context)
            except Exception:
                pass
        bpy.ops.wm.quit_blender()


pkg.register()
win, area, region = view()
with bpy.context.temp_override(window=win, area=area, region=region,
                               space_data=area.spaces.active):
    bpy.ops.mc_blender.play("INVOKE_DEFAULT", seed=20240501, render_distance=4,
                            creative=True)
bpy.app.timers.register(Probe().tick, first_interval=0.3, persistent=True)
