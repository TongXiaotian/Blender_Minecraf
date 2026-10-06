"""定向实验：到底是"改网格"还是"其它每帧写入"让主循环卡住。

用法：blender --factory-startup --python tools/probe_loop.py -- [输出json]

阶段：
  A 冻结（什么都不做）            -> 基线帧率
  B 只跑逻辑（物理/相机/射线），不重建任何网格
  C 每 tick 额外重建 1 个区块网格（模拟流式加载）
  D 每 tick 把相机平移 1e-5（模拟"每帧写属性"）
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

OUT = os.path.join(ROOT, "build", "probe_loop.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)


class Probe:
    PHASES = [
        ("A 逻辑 only", dict(frozen=False, stream=False, rebuild=0, cam_jiggle=False)),
        ("B 每帧重建1个区块", dict(frozen=False, stream=False, rebuild=1, cam_jiggle=False)),
        ("C 每帧重建2个区块", dict(frozen=False, stream=False, rebuild=2, cam_jiggle=False)),
        ("D 完整流式(实际游戏)", dict(frozen=False, stream=True, rebuild=0, cam_jiggle=False)),
    ]

    def __init__(self):
        self.t0 = time.time()
        self.ready = False
        self.idx = -1
        self.t_start = 0.0
        self.t_ticks0 = 0
        self.results = []
        self.perf0 = {}

    def tick(self):
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        if game is None:
            bpy.ops.wm.quit_blender()
            return None
        now = time.time()
        if not self.ready:
            if game.mode == "playing" or now - self.t0 > 40:
                self.ready = True
                print(f"[PROBE] 载入完成 {now-self.t0:.1f}s 区块 {len(game.world.chunks)}")
                self.next()
            return 0.05
        if now - self.t_start > 2.0:
            n = game.perf["ticks"] - self.t_ticks0
            span = now - self.t_start
            detail = {k[2:]: round((v - self.perf0.get(k, 0.0)) / max(1, n) * 1000, 1)
                      for k, v in game.perf.items() if k.startswith("t_")}
            self.results.append({"phase": self.PHASES[self.idx][0],
                                 "ticks_per_sec": round(n / span, 1),
                                 "frame_ms": round(span / max(1, n) * 1000, 1),
                                 "ms": detail,
                                 "chunks": len(game.world.chunks)})
            print("[PROBE]", self.results[-1])
            if not self.next():
                self.finish()
                return None
        return 0.05

    def next(self):
        self.idx += 1
        if self.idx >= len(self.PHASES):
            return False
        name, cfg = self.PHASES[self.idx]
        game = mc_game._ACTIVE_INSTANCE[0]
        game.frozen = cfg["frozen"]
        game.no_stream = not cfg["stream"]
        game._probe_rebuild = cfg["rebuild"]
        game._probe_jiggle = cfg["cam_jiggle"]
        game.perf["ticks"] = 0
        self.perf0 = {k: v for k, v in game.perf.items() if k.startswith("t_")}
        self.t_ticks0 = 0
        self.t_start = time.time()
        print(f"[PROBE] 阶段 {name}")
        return True

    def finish(self):
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({"results": self.results,
                       "draw_errors": mc_game.DRAW_ERRORS[:5],
                       "tick_errors": mc_game.TICK_ERRORS[:5]},
                      fh, ensure_ascii=False, indent=2)
        print("[PROBE] 写入", OUT)
        bpy.ops.wm.quit_blender()


# 给操作符打补丁：可选的"每帧重建"和"每帧写相机"
def _patch():
    orig_tick = mc_game.MC_Game._tick

    def tick_wrapper(self, context):
        if getattr(self, "_probe_jiggle", False) and not self.frozen:
            loc = self.cam.location
            self.cam.location = (loc[0] + 1e-5, loc[1], loc[2])
        if getattr(self, "_probe_rebuild", 0) and not self.frozen:
            for i in range(self._probe_rebuild):
                key = list(self.world.chunks.keys())
                if key:
                    cx, cz = key[(i + int(time.time() * 10)) % len(key)]
                    ch = self.world.chunks[(cx, cz)]
                    self._build_mesh(cx, cz)
        orig_tick(self, context)

    mc_game.MC_Game._tick = tick_wrapper


_patch()
pkg.register()
win = bpy.context.window_manager.windows[0]
area = next(a for a in win.screen.areas if a.type == "VIEW_3D")
region = next(r for r in area.regions if r.type == "WINDOW")
with bpy.context.temp_override(window=win, area=area, region=region,
                               space_data=area.spaces.active):
    bpy.ops.mc_blender.play("INVOKE_DEFAULT", seed=20240501, render_distance=4,
                            creative=True)
bpy.app.timers.register(Probe().tick, first_interval=0.2, persistent=True)
