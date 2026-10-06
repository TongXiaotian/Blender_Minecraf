"""GUI 端到端测试：真实事件驱动（--enable-event-simulate），截图 + 诊断。

用法：
    blender --enable-event-simulate --factory-startup --python tools/gui_test.py -- \
        [总时长] [游戏截图] [物品栏截图]

流程：注册插件 → 用真实点击关掉启动画面 → 开始游戏 → 用 event_simulate 发真实按键
（前进/转视角/挖掘/放置/物品栏/F3/菜单）→ 截图（含 HUD）→ 写诊断 json → 退出。
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

import blender_minecraft as pkg                    # noqa: E402
import blender_minecraft.mc_game as mc_game        # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
DURATION = float(argv[0]) if argv else 16.0
SHOT = argv[1] if len(argv) > 1 else os.path.join(ROOT, "shot_game.png")
SHOT2 = argv[2] if len(argv) > 2 else os.path.join(ROOT, "shot_inventory.png")
RESULT = os.path.join(ROOT, "build", "gui_result.json")
os.makedirs(os.path.dirname(RESULT), exist_ok=True)

DATA = {"blender": bpy.app.version_string, "steps": []}


def log(msg):
    print("[GUI-TEST]", msg, flush=True)
    DATA["steps"].append(str(msg))


def view():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            return win, area, next((r for r in area.regions if r.type == "WINDOW"), None)
    return None, None, None


def sim(etype, value="PRESS", dx=0, dy=0, unicode=""):
    """发一个真实事件给 Blender。"""
    win, area, region = view()
    if win is None or region is None:
        return
    x = region.x + region.width // 2 + dx
    y = region.y + region.height // 2 + dy
    kw = {"type": etype, "value": value, "x": x, "y": y}
    if unicode:
        kw["unicode"] = unicode
    try:
        win.event_simulate(**kw)
    except Exception as exc:
        log(f"事件 {etype} 失败: {type(exc).__name__}: {exc}")


class Sim:
    def __init__(self):
        self.t0 = time.time()
        self.started = False
        self.phase = 0
        self.peak_chunks = 0
        self.peak_faces = 0
        self.fps_samples = []
        self.load_time = None

    def tick(self):
        elapsed = time.time() - self.t0
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        if game is not None:
            if game.mode != "loading" and self.load_time is None:
                self.load_time = round(elapsed, 1)
                log(f"载入完成，用时 {self.load_time}s，区块 {len(game.world.chunks)}")
            self.peak_chunks = max(self.peak_chunks, len(game.world.chunks))
            try:
                faces = sum(len(o.data.polygons) for o in bpy.data.objects
                            if o.name.startswith("MC_chunk_") and o.data)
                self.peak_faces = max(self.peak_faces, faces)
            except Exception:
                pass
            self.fps_samples.append([round(elapsed, 1), round(float(game.fps), 1),
                                     game.mode, len(game.world.chunks)])

        # 0.3s：点一下关掉启动画面
        if self.phase == 0 and elapsed > 0.4:
            self.phase = 1
            sim("LEFTMOUSE", "PRESS", dx=700, dy=380)
            sim("LEFTMOUSE", "RELEASE", dx=700, dy=380)
            log("已点击关闭启动画面")
        # 1.0s：开始游戏
        elif self.phase == 1 and elapsed > 1.2:
            self.phase = 2
            win, area, region = view()
            with bpy.context.temp_override(window=win, area=area, region=region,
                                           space_data=area.spaces.active):
                bpy.ops.mc_blender.play("INVOKE_DEFAULT", seed=20240501,
                                        render_distance=4, creative=True,
                                        quality="medium")
            g = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
            log(f"游戏已启动: {g is not None} 模式={getattr(g, 'mode', None)}")
        # 载入完成后开始模拟操作
        elif self.phase == 2 and game is not None and game.mode != "loading" \
                and game.player.on_ground:
            self.phase = 3
            self.phase_t = elapsed
            # 低头看地面，便于挖掘/放置测试
            game.player.pitch = -1.25
            game.player.yaw = 0.0
            import math as _m
            px = int(_m.floor(game.player.pos[0]))
            py = int(_m.floor(game.player.pos[1]))
            pz = int(_m.floor(game.player.pos[2]))
            self.centre = (px, py, pz)
            self.solid_before = self.count_solid(game, self.centre)
            sim("LEFTMOUSE", "PRESS")
            log(f"模拟：低头挖掘 玩家=({game.player.pos[0]:.1f},"
                f"{game.player.pos[1]:.1f},{game.player.pos[2]:.1f}) "
                f"周围实心方块={self.solid_before}")
        elif self.phase == 3 and elapsed - self.phase_t > 0.35:
            self.phase = 3.5
            tgt = game.target
            if tgt is not None:
                self.aim_pos = tgt[0]
                self.aim_bid = game.world.get_block(*tgt[0])
                log(f"准星目标位置={tgt[0]} 方块={self.aim_bid} "
                    f"(准星与射线一致)")
            log(f"诊断：mouse_left={game.mouse_left} creative={game.player.creative}")
        elif self.phase == 3.5 and elapsed - self.phase_t > 1.5:
            self.phase = 4
            sim("LEFTMOUSE", "RELEASE")
            self.solid_after = self.count_solid(game, self.centre)
            aim_now = None
            if getattr(self, "aim_pos", None):
                aim_now = game.world.get_block(*self.aim_pos)
            self.aim_after = aim_now
            log(f"挖掘后：周围实心方块 {self.solid_before} → {self.solid_after}，"
                f"准星处方块 {getattr(self, 'aim_bid', None)} → {aim_now}")
            sim("RIGHTMOUSE", "PRESS")
            log("模拟：右键放置")
        elif self.phase == 4 and elapsed - self.phase_t > 1.9:
            self.phase = 5
            sim("RIGHTMOUSE", "RELEASE")
            self.solid_placed = self.count_solid(game, self.centre)
            log(f"放置后：周围实心方块={self.solid_placed}")
            self.slot_before_pick = game.inv.held_name()
            tgt = game.target
            self.pick_target = (tgt[2] if tgt else None)
            sim("MIDDLEMOUSE", "PRESS")
            sim("MIDDLEMOUSE", "RELEASE")
            log("模拟：中键取方块")
        elif self.phase == 5 and elapsed - self.phase_t > 2.2:
            self.phase = 6
            self.slot_after = game.inv.held_name()
            log(f"中键取方块：目标方块id={self.pick_target} "
                f"快捷栏 {self.slot_before_pick} → {self.slot_after}")
            sim("SPACE", "PRESS")
            sim("SPACE", "RELEASE")
            log("模拟：跳跃")
        elif self.phase == 6 and elapsed - self.phase_t > 2.4:
            self.phase = 7
            self.shot(SHOT, "游戏画面")
        elif self.phase == 7 and elapsed - self.phase_t > 2.8:
            self.phase = 8
            sim("E", "PRESS")
            sim("E", "RELEASE")
            log("模拟：打开物品栏")
        elif self.phase == 8 and elapsed - self.phase_t > 3.6:
            self.phase = 9
            self.shot(SHOT2, "物品栏")
            sim("E", "PRESS")
            sim("E", "RELEASE")
        elif self.phase == 9 and elapsed - self.phase_t > 4.1:
            self.phase = 10
            sim("F3", "PRESS")
            sim("F3", "RELEASE")
            log("模拟：F3 调试信息")
        elif self.phase == 10 and elapsed - self.phase_t > 5.0:
            self.phase = 11
            sim("ESC", "PRESS")
            sim("ESC", "RELEASE")
            log("模拟：Esc 菜单")
        elif self.phase == 11 and elapsed - self.phase_t > 5.8:
            self.phase = 12
            self.shot(os.path.join(ROOT, "shot_pause.png"), "暂停菜单")
        elif self.phase == 12 and elapsed - self.phase_t > 6.4:
            self.phase = 13
            sim("ESC", "PRESS")
            sim("ESC", "RELEASE")
            log("模拟：回到游戏（等它稳定下来再截最终图）")
        elif elapsed > DURATION - 2.0 and self.phase == 13:
            self.phase = 14
            game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
            if game is not None:
                game.player.pitch = -0.22
                log(f"稳定期：FPS={game.fps:.1f} 区块={len(game.world.chunks)}")
            self.shot(SHOT, "稳定后的游戏画面")
        elif elapsed > DURATION:
            self.finish()
            return None
        return 0.15

    def count_solid(self, game, centre, r=3):
        cx, cy, cz = centre
        n = 0
        for x in range(cx - r, cx + r + 1):
            for y in range(cy - r, cy + r + 1):
                for z in range(cz - r, cz + r + 1):
                    if game.world.get_block(x, y, z) != 0:
                        n += 1
        return n

    def shot(self, path, label):
        win, area, region = view()
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.screen.screenshot_area(filepath=path)
            log(f"截图 {label}: {os.path.basename(path)} "
                f"({os.path.getsize(path)/1024:.0f} KB)")
        except Exception as exc:
            log(f"截图失败 {label}: {type(exc).__name__}: {exc}")

    def finish(self):
        game = mc_game._ACTIVE_INSTANCE[0] if mc_game._ACTIVE_INSTANCE else None
        DATA.update({
            "load_time_s": self.load_time,
            "peak_chunks": self.peak_chunks,
            "peak_faces": self.peak_faces,
            "gameplay": {
                "centre": getattr(self, "centre", None),
                "solid_before_dig": getattr(self, "solid_before", None),
                "solid_after_dig": getattr(self, "solid_after", None),
                "solid_after_place": getattr(self, "solid_placed", None),
                "aim_pos": getattr(self, "aim_pos", None),
                "aim_block_before": getattr(self, "aim_bid", None),
                "aim_block_after": getattr(self, "aim_after", None),
                "slot_before_pick": getattr(self, "slot_before_pick", None),
                "slot_after_pick": getattr(self, "slot_after", None),
                "pick_target_id": getattr(self, "pick_target", None),
            },
            "draw_errors": mc_game.DRAW_ERRORS[:12],
            "tick_errors": mc_game.TICK_ERRORS[:12],
            "mode": getattr(game, "mode", None),
            "fps": round(float(getattr(game, "fps", 0.0)), 1),
            "player": [round(float(v), 2) for v in game.player.pos] if game else None,
            "on_ground": bool(game.player.on_ground) if game else None,
            "chunks": len(game.world.chunks) if game else 0,
            "perf": {k: round(v, 3) for k, v in game.perf.items()} if game else None,
            "chat": [c["text"] for c in game.chat[-6:]] if game else [],
            "fps_samples": self.fps_samples[-20:],
        })
        with open(RESULT, "w", encoding="utf-8") as fh:
            json.dump(DATA, fh, ensure_ascii=False, indent=2)
        log(f"绘制异常 {len(mc_game.DRAW_ERRORS)} 条，逻辑异常 {len(mc_game.TICK_ERRORS)} 条")
        for line in mc_game.DRAW_ERRORS[:4]:
            log("  DRAW: " + line)
        for line in mc_game.TICK_ERRORS[:6]:
            log("  TICK: " + (line.splitlines()[0] if line else ""))
        if game is not None:
            try:
                game._shutdown(bpy.context)
            except Exception:
                pass
        log("完成，退出 Blender")
        bpy.ops.wm.quit_blender()


pkg.register()
log("插件已注册")
bpy.app.timers.register(Sim().tick, first_interval=0.2, persistent=True)
