"""游戏主循环：一个模态操作符，接管 3D 视图的输入与绘制。

* 鼠标被"捕获"（每帧 warp 到视口中心）实现第一人称视角；
* 计时器驱动 60Hz 的逻辑帧：物理、区块流式加载、挖掘进度、昼夜；
* 两个绘制回调：POST_VIEW 画方块选中框，POST_PIXEL 画整个 HUD。
"""
from __future__ import annotations

import math
import os
import time

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Vector

from . import mc_blocks as B
from . import mc_render, mc_save, mc_world
from .mc_const import (CHUNK_X, CHUNK_Z, DEFAULT_RENDER_DISTANCE, FOV,
                       MAX_RENDER_DISTANCE, PLAYER_EYE, SEA_LEVEL, WORLD_H)
from .mc_inventory import Inventory, Slot
from .mc_player import Player
from .mc_raycast import raycast
from .mc_textures import TILE_INDEX
from .mc_ui import (UI, death_layout, hotbar_layout, inventory_layout,
                    inventory_slot_rects, pause_layout, point_in)

FACING = [("南", 0), ("西南", 45), ("西", 90), ("西北", 135),
          ("北", 180), ("东北", 225), ("东", 270), ("东南", 315)]

# 诊断用：绘制/逻辑帧里被吞掉的异常
DRAW_ERRORS: list = []
TICK_ERRORS: list = []
# 当前正在运行的实例（自动化测试用）
_ACTIVE_INSTANCE: list = []


class _FakeEvent:
    """给自动化测试用的假事件。"""

    def __init__(self, etype, value="PRESS", x=0, y=0, unicode=""):
        self.type = etype
        self.value = value
        self.mouse_x = x
        self.mouse_y = y
        self.unicode = unicode


def _facing_name(yaw_deg: float) -> str:
    d = (yaw_deg + 180.0) % 360.0
    best = min(FACING, key=lambda f: min(abs(f[1] - d), 360 - abs(f[1] - d)))
    return best[0]


class MC_Game(bpy.types.Operator):
    """在 3D 视图里开始一局《我的世界》风格的游戏。"""

    bl_idname = "mc_blender.play"
    bl_label = "开始游戏"
    bl_description = "在当前 3D 视图里生成一个方块世界并开始游玩"
    bl_options = {"REGISTER"}

    seed: bpy.props.IntProperty(name="世界种子", default=0, min=0)
    render_distance: bpy.props.IntProperty(
        name="渲染距离", default=DEFAULT_RENDER_DISTANCE, min=2,
        max=MAX_RENDER_DISTANCE, subtype="NONE")
    creative: bpy.props.BoolProperty(name="创造模式", default=True)
    quality: bpy.props.EnumProperty(
        name="画质", default="medium",
        items=[("high", "高（阴影+TAA4）", "画面最好，最吃显卡"),
               ("medium", "中（阴影+TAA1）", "推荐"),
               ("low", "低（关阴影）", "核显/老显卡推荐")])

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def invoke(self, context, event):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "请把鼠标放到 3D 视图里再开始游戏")
            return {"CANCELLED"}
        if context.region is None or context.region.type != "WINDOW":
            self.report({"ERROR"}, "请在 3D 视图的主区域里开始游戏")
            return {"CANCELLED"}

        self.area = context.area
        self.area_ptr = context.area.as_pointer()
        self.region = context.region
        self.window = context.window
        self.space = context.space_data
        self.scene = context.scene
        self._remember_view_state()

        if self.seed == 0:
            self.seed = int.from_bytes(os.urandom(4), "little") % 2000000000

        # ---- 世界 / 玩家 ----
        self.world = mc_world.World(seed=self.seed)
        self.spawn = self._find_spawn()
        self.player = Player(spawn=self.spawn, creative=bool(self.creative))
        self.inv = Inventory(creative=bool(self.creative))
        if self.creative:
            self.inv.fill_creative()
        else:
            for name in ("stone", "cobblestone", "dirt", "oak_planks", "sand",
                         "glass", "oak_log", "torch", "glowstone"):
                if name in B.BY_NAME:
                    self.inv.add(name, 64)

        # ---- 场景 ----
        mc_render.ensure_world_lighting()
        self.mats = mc_render.ensure_materials()
        self.cam = mc_render.ensure_camera()
        self._hide_other_objects()
        self._apply_view_state()

        # ---- 状态 ----
        self.mode = "loading"
        self.keys: set = set()
        self.mouse_left = False
        self.mouse_right = False
        self.mouse_px = (0, 0)
        self.target = None
        self.break_progress = 0.0
        self.break_cooldown = 0.0
        self.break_pos = None
        self.place_cooldown = 0.0
        self.chat: list = []
        self.chat_input = ""
        self.chat_open_prefix = ""
        self.debug = False
        self.hud_visible = True
        self.third_person = False
        self.time_of_day = 0.15
        self.day_seconds = 1200.0
        self.fps = 60.0
        self._frame_times: list = []
        self._last_tick = time.perf_counter()
        self._mesh_ms = 0.0
        self._item_name = ""
        self._item_name_timer = 0.0
        self._fly_tap = 0.0
        self._rd = int(self.render_distance)
        self._offsets = sorted(
            [(dx, dz) for dx in range(-self._rd - 3, self._rd + 4)
             for dz in range(-self._rd - 3, self._rd + 4)],
            key=lambda o: o[0] * o[0] + o[1] * o[1])
        self._loading_total = 0
        self._loading_done = 0
        self._warmup_elapsed = 0.0
        self._warmup_total = 40.0
        self._warmup_forces = 0
        self._warmup_ready = 0
        self._warmup_need = 0
        self._gl_cost = 99.0
        self._gl_last = 0.0
        self._gl_tries = 0
        self.perf = {"gen": 0.0, "mesh": 0.0, "n": 0, "ticks": 0,
                     "load_calls": 0, "loading": 0.0, "play_ticks": 0,
                     "t_phys": 0.0, "t_stream": 0.0, "t_target": 0.0,
                     "t_cam": 0.0, "t_sky": 0.0, "t_tick": 0.0,
                     "t_meshdata": 0.0, "t_meshobj": 0.0}
        self._obj_cache: dict = {}
        self._last_player_chunk = None
        self.loading_budget = 0.8
        self.frozen = False
        self.no_stream = False
        self._sky_timer = 0.0
        self._sky_applied = False
        self._sky_color = None
        self._dt = 0.0

        # ---- UI ----
        self.ui = UI()
        self.ui.ensure(mc_render.ensure_atlas())
        self.ui.set_region(self.region.width, self.region.height)

        # ---- 回调 ----
        self._hud_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_hud, (), "WINDOW", "POST_PIXEL")
        self._line_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_lines, (), "WINDOW", "POST_VIEW")
        self._timer = context.window_manager.event_timer_add(1.0 / 60.0,
                                                            window=self.window)
        context.window_manager.modal_handler_add(self)
        # 预生成出生点附近的区块
        self._prepare_loading()
        self.window.cursor_warp(self.region.x + self.region.width // 2,
                                self.region.y + self.region.height // 2)
        _ACTIVE_INSTANCE.clear()
        _ACTIVE_INSTANCE.append(self)
        return {"RUNNING_MODAL"}

    # 供自动化测试直接驱动事件
    def handle_test_event(self, spec: dict):
        ev = _FakeEvent(spec.get("type", "TIMER"), spec.get("value", "PRESS"),
                        spec.get("mouse_x", 0), spec.get("mouse_y", 0),
                        spec.get("unicode", ""))
        return self._handle_event(bpy.context, ev)

    # ------------------------------------------------------------------
    def _find_spawn(self):
        best = None
        for cx in (-1, 0, 1):
            for cz in (-1, 0, 1):
                self.world.get_chunk(cx, cz)
        for r in range(0, 40):
            for (dx, dz) in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r),
                             (r, -r), (-r, r)):
                x, z = dx, dz
                h = self.world.highest_solid(x, z)
                if h < SEA_LEVEL + 1:
                    continue
                bid = self.world.get_block(x, h, z)
                if B.LIQUID_TABLE[bid]:
                    continue
                best = (x + 0.5, float(h + 1), z + 0.5)
                return best
        return (0.5, 80.0, 0.5)

    # ------------------------------------------------------------------
    # 视图状态保存 / 恢复
    # ------------------------------------------------------------------
    def _remember_view_state(self):
        sp = self.space
        r3d = sp.region_3d
        sh = sp.shading
        self._prev = {
            "view_perspective": r3d.view_perspective,
            "camera": sp.camera,
            "shading_type": sh.type,
            "color_type": sh.color_type,
            "background_type": sh.background_type,
            "background_color": tuple(sh.background_color),
            "show_shadows": sh.show_shadows,
            "show_gizmo": sp.show_gizmo,
            "overlays": sp.overlay.show_overlays,
            "hide_objects": [(o, o.hide_viewport, o.hide_render)
                             for o in bpy.data.objects],
        }

    def _hide_other_objects(self):
        for obj in bpy.data.objects:
            if obj.name.startswith("MC_"):
                continue
            obj.hide_viewport = True
            obj.hide_render = True

    def _apply_view_state(self):
        sp, sh = self.space, self.space.shading
        sp.region_3d.view_perspective = "CAMERA"
        sp.camera = self.cam
        try:
            sh.type = "MATERIAL"
        except TypeError:
            sh.type = "SOLID"
        sh.color_type = "MATERIAL"
        sh.light = "STUDIO"
        sh.show_shadows = True
        sh.show_cavity = False
        sh.background_type = "VIEWPORT"
        sh.background_color = (0.45, 0.62, 0.90)
        try:
            sh.use_scene_lights = True
            sh.use_scene_world = True
        except AttributeError:
            pass
        # 视口默认 TAA 采样是 16：场景每帧都在变时 EEVEE 会真的渲染 16 遍，
        # 这是"每帧几秒"的真正原因。设成 1 后回到 60fps。
        try:
            self._prev_taa = self.scene.eevee.taa_samples
            self.scene.eevee.taa_samples = 1 if self.quality != "high" else 4
            # 关掉 EEVEE 的实时全局光/反射：方块场景每帧都在变，
            # 开着它 Blender 会不停重烤探针，帧率会掉到个位数。
            # AO 与面明暗我们已经烘焙进顶点色了，画面损失很小。
            self._prev_gi = {}
            for key, val in (("use_raytracing", False), ("use_fast_gi", False)):
                try:
                    self._prev_gi[key] = getattr(self.scene.eevee, key)
                    setattr(self.scene.eevee, key, val)
                except Exception:
                    continue
        except Exception:
            self._prev_taa = None
            self._prev_gi = {}
        if self.quality == "low":
            self.space.shading.show_shadows = False
        # 色彩管理改成 Standard：Minecraft 那种鲜艳直出的观感（AgX 会发灰）
        try:
            self._prev_view_transform = self.scene.view_settings.view_transform
            self._prev_look = self.scene.view_settings.look
            self.scene.view_settings.view_transform = "Standard"
            self.scene.view_settings.look = "None"
        except Exception:
            self._prev_view_transform = None
            self._prev_look = None
        sp.overlay.show_overlays = False
        try:
            sp.show_gizmo = False
        except AttributeError:
            pass
        r3d = sp.region_3d
        r3d.view_location = (0.0, 0.0, 0.0)

    def _restore_view_state(self):
        try:
            sp = self.space
            r3d = sp.region_3d
            sh = sp.shading
            prev = self._prev
            r3d.view_perspective = prev["view_perspective"]
            sp.camera = prev["camera"]
            sh.type = prev["shading_type"]
            sh.color_type = prev["color_type"]
            sh.background_type = prev["background_type"]
            sh.background_color = prev["background_color"]
            sh.show_shadows = prev["show_shadows"]
            if getattr(self, "_prev_taa", None) is not None:
                self.scene.eevee.taa_samples = self._prev_taa
            for key, val in (getattr(self, "_prev_gi", None) or {}).items():
                try:
                    setattr(self.scene.eevee, key, val)
                except Exception:
                    pass
            if getattr(self, "_prev_view_transform", None) is not None:
                self.scene.view_settings.view_transform = self._prev_view_transform
                self.scene.view_settings.look = self._prev_look
            sp.show_gizmo = prev["show_gizmo"]
            sp.overlay.show_overlays = prev["overlays"]
            for obj, hv, hr in prev["hide_objects"]:
                try:
                    obj.hide_viewport = hv
                    obj.hide_render = hr
                except ReferenceError:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 载入阶段
    # ------------------------------------------------------------------
    def _prepare_loading(self):
        pcx = int(math.floor(self.player.pos[0] / CHUNK_X))
        pcz = int(math.floor(self.player.pos[2] / CHUNK_Z))
        # 先把整个渲染范围内的空网格对象建好：
        # 玩的时候只是"填充几何"，不用新建对象（新建对象会触发一次昂贵的同步）
        rd = self._rd
        for (dx, dz) in self._offsets:
            if dx * dx + dz * dz > (rd + 1) ** 2:
                continue
            cx, cz = pcx + dx, pcz + dz
            obj = bpy.data.objects.get(f"MC_chunk_{cx}_{cz}")
            if obj is None:
                obj = mc_render.build_chunk_object(cx, cz, None, self.mats,
                                                   visible=False)
                if obj is not None:
                    self._obj_cache[(cx, cz)] = obj
        self._loading_list = []
        for (dx, dz) in self._offsets:
            if dx * dx + dz * dz <= (min(self._rd, 2) + 0.5) ** 2:
                self._loading_list.append((pcx + dx, pcz + dz))
        self._loading_total = max(1, len(self._loading_list))
        self._loading_done = 0

    def _loading_step(self):
        t0 = time.perf_counter()
        self.perf["calls"] = self.perf.get("calls", 0) + 1
        while self._loading_list and time.perf_counter() - t0 < self.loading_budget:
            cx, cz = self._loading_list.pop(0)
            tg = time.perf_counter()
            self.world.get_chunk(cx, cz)
            t1 = time.perf_counter()
            self._build_mesh(cx, cz, show=False)
            t2 = time.perf_counter()
            self.perf["gen"] += t1 - tg
            self.perf["mesh"] += t2 - t1
            self.perf["n"] += 1
            self._loading_done += 1
        # 玩家脚下的地形一定要先建好
        px, pz = self.player.pos[0], self.player.pos[2]
        if not self.world.has_chunk(int(px // CHUNK_X), int(pz // CHUNK_Z)):
            self.world.get_chunk(int(px // CHUNK_X), int(pz // CHUNK_Z))
        if not self._loading_list:
            # 先切到"准备渲染"阶段：把渲染距离内的区块建完 + 触发着色器编译，
            # 这期间视口是空的，用进度界面盖住。
            self._show_all_chunks()
            self.mode = "warmup"
            self._warmup_elapsed = 0.0
            self._warmup_forces = 0

    def _start_playing(self):
        self.mode = "playing"
        self._last_tick = time.perf_counter()
        self.chat_msg("欢迎来到 Blender 我的世界！ WASD 移动，左键挖，右键放，E 打开物品栏")
        self.chat_msg("按 F3 看调试信息，Esc 打开菜单")

    def _show_all_chunks(self):
        """载入结束后把近处区块显示出来。"""
        for (cx, cz) in list(self.world.chunks.keys()):
            obj = self._obj_cache.get((cx, cz))
            if obj is None:
                obj = bpy.data.objects.get(f"MC_chunk_{cx}_{cz}")
                if obj is not None:
                    self._obj_cache[(cx, cz)] = obj
            if obj is not None and obj.hide_viewport:
                obj.hide_viewport = False

    def _build_mesh(self, cx, cz, show=True):
        ch = self.world.chunks.get((cx, cz))
        if ch is None:
            return
        t0 = time.perf_counter()
        data = mc_mesher_build(self.world, ch)
        t1 = time.perf_counter()
        obj = mc_render.build_chunk_object(cx, cz, data, self.mats, visible=show)
        t2 = time.perf_counter()
        self.perf["t_meshdata"] += t1 - t0
        self.perf["t_meshobj"] += t2 - t1
        if obj is not None:
            self._obj_cache[(cx, cz)] = obj
        ch.dirty = False

    def _update_chunk_visibility(self, pcx, pcz):
        """只在玩家跨区块时调用：隐藏/显示 / 卸载远处区块。"""
        rd = self._rd
        hide2 = (rd + 1) ** 2
        del2 = (rd + 6) ** 2
        for (cx, cz) in list(self.world.chunks.keys()):
            ddx, ddz = cx - pcx, cz - pcz
            d2 = ddx * ddx + ddz * ddz
            obj = self._obj_cache.get((cx, cz))
            if obj is None:
                obj = bpy.data.objects.get(f"MC_chunk_{cx}_{cz}")
                if obj is not None:
                    self._obj_cache[(cx, cz)] = obj
            if obj is not None:
                want_hidden = d2 > hide2
                if obj.hide_viewport != want_hidden:
                    obj.hide_viewport = want_hidden
            if d2 > del2:
                mc_render.remove_chunk_object(cx, cz)
                self._obj_cache.pop((cx, cz), None)
                del self.world.chunks[(cx, cz)]

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def modal(self, context, event):
        if context.area is None or context.area.as_pointer() != self.area_ptr:
            self._shutdown(context)
            return {"CANCELLED"}

        if event.type == "TIMER":
            try:
                self._tick(context)
            except Exception as exc:
                import traceback
                TICK_ERRORS.append(f"{type(exc).__name__}: {exc}")
                TICK_ERRORS.append(traceback.format_exc())
                if len(TICK_ERRORS) > 40:
                    del TICK_ERRORS[:20]
            return {"RUNNING_MODAL"}

        try:
            return self._handle_event(context, event)
        except Exception as exc:
            import traceback
            TICK_ERRORS.append(f"event {event.type}: {type(exc).__name__}: {exc}")
            TICK_ERRORS.append(traceback.format_exc())
            return {"RUNNING_MODAL"}

    # ---------------- 输入 ----------------
    KEYMAP = {
        "W": "forward", "S": "back", "A": "left", "D": "right",
        "SPACE": "jump", "LEFT_SHIFT": "sneak", "RIGHT_SHIFT": "sneak",
        "LEFT_CTRL": "sprint", "RIGHT_CTRL": "sprint",
    }

    def _handle_event(self, context, event):
        # 鼠标位置（视口内像素，左下角原点）
        if event.type in {"MOUSEMOVE", "LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE",
                          "WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            self.mouse_px = (event.mouse_x - self.region.x,
                             event.mouse_y - self.region.y)

        if self.mode == "chat":
            return self._chat_event(event)
        if self.mode == "dead":
            return self._menu_event(event, death_layout(self.ui.w / 2, self.ui.h / 2),
                                    self._death_action)
        if self.mode == "pause":
            lay = pause_layout(self.ui.w / 2, self.ui.h / 2, self._rd)
            return self._menu_event(event, lay, self._pause_action)
        if self.mode == "inventory":
            return self._inventory_event(event)

        if self.mode != "playing":
            return {"RUNNING_MODAL"}

        # ---------------- 游戏中 ----------------
        if event.type == "MOUSEMOVE":
            self._mouse_look(event)
            return {"RUNNING_MODAL"}

        if event.type in self.KEYMAP:
            action = self.KEYMAP[event.type]
            if event.value == "PRESS":
                if action == "jump":
                    now = time.perf_counter()
                    if self.player.creative and now - self._fly_tap < 0.32:
                        self.player.flying = not self.player.flying
                        self._fly_tap = 0.0
                        self.chat_msg("飞行模式：" + ("开" if self.player.flying else "关"))
                    else:
                        self._fly_tap = now
                self.keys.add(action)
            else:
                self.keys.discard(action)
            return {"RUNNING_MODAL"}

        if event.value == "PRESS" and event.type in {
                "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"}:
            name = event.type
            num = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN",
                   "EIGHT", "NINE").index(name)
            self.inv.select(num)
            self._show_item_name()
            return {"RUNNING_MODAL"}

        if event.value == "PRESS":
            if event.type == "E":
                self.mode = "inventory"
                self._release_all_keys()
                return {"RUNNING_MODAL"}
            if event.type == "T":
                self.mode = "chat"
                self.chat_input = ""
                self.chat_open_prefix = ""
                self._release_all_keys()
                return {"RUNNING_MODAL"}
            if event.type == "SLASH":
                self.mode = "chat"
                self.chat_input = "/"
                self.chat_open_prefix = "/"
                self._release_all_keys()
                return {"RUNNING_MODAL"}
            if event.type == "Q":
                self._drop_item()
                return {"RUNNING_MODAL"}
            if event.type == "ESC":
                self.mode = "pause"
                self._release_all_keys()
                return {"RUNNING_MODAL"}
            if event.type == "F1":
                self.hud_visible = not self.hud_visible
                return {"RUNNING_MODAL"}
            if event.type == "F3":
                self.debug = not self.debug
                return {"RUNNING_MODAL"}
            if event.type == "F5":
                self.third_person = not self.third_person
                return {"RUNNING_MODAL"}
            if event.type == "G":
                self._toggle_gamemode()
                return {"RUNNING_MODAL"}

        if event.type == "WHEELUPMOUSE":
            self.inv.scroll(-1)
            self._show_item_name()
            return {"RUNNING_MODAL"}
        if event.type == "WHEELDOWNMOUSE":
            self.inv.scroll(1)
            self._show_item_name()
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE":
            self.mouse_left = event.value == "PRESS"
            return {"RUNNING_MODAL"}
        if event.type == "RIGHTMOUSE":
            self.mouse_right = event.value == "PRESS"
            if event.value == "PRESS":
                self._use_item()
            return {"RUNNING_MODAL"}
        if event.type == "MIDDLEMOUSE" and event.value == "PRESS":
            self._pick_block()
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _release_all_keys(self):
        self.keys.clear()
        self.mouse_left = False
        self.mouse_right = False

    def _mouse_look(self, event):
        mx = event.mouse_x - self.region.x
        my = event.mouse_y - self.region.y
        cx = self.region.width // 2
        cy = self.region.height // 2
        dx = mx - cx
        dy = my - cy
        if dx or dy:
            self.player.yaw -= dx * 0.0022
            self.player.pitch -= dy * 0.0022
            self.player.pitch = max(-math.pi / 2 + 0.001,
                                    min(math.pi / 2 - 0.001, self.player.pitch))
            self.player.yaw %= math.tau
            self.window.cursor_warp(self.region.x + cx, self.region.y + cy)

    # ---------------- 菜单事件 ----------------
    def _menu_event(self, event, layout, action_fn):
        if event.type == "MOUSEMOVE":
            return {"RUNNING_MODAL"}
        if event.type == "ESC" and event.value == "PRESS":
            if self.mode == "pause":
                self.mode = "playing"
                self._last_tick = time.perf_counter()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            ux = self.mouse_px[0] / self.ui.scale
            uy = self.mouse_px[1] / self.ui.scale
            for label, rect, act in layout:
                if point_in(rect, ux, uy):
                    action_fn(act)
                    break
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def _pause_action(self, action):
        if action == "resume":
            self.mode = "playing"
            self._last_tick = time.perf_counter()
        elif action == "save":
            path = mc_save.save_world(self.world, self.player, self.inv)
            self.chat_msg("已保存：" + path)
        elif action == "load":
            got = mc_save.load_world()
            if got is None:
                self.chat_msg("没有找到存档")
            else:
                self._adopt_world(*got)
                self.chat_msg("存档已载入")
                self.mode = "playing"
        elif action == "render":
            self._rd = 2 if self._rd >= MAX_RENDER_DISTANCE else self._rd + 2
            self._rebuild_offsets()
            self.chat_msg(f"渲染距离 = {self._rd} 区块")
        elif action == "gamemode":
            self._toggle_gamemode()
        elif action == "quit":
            self._shutdown(bpy.context)

    def _death_action(self, action):
        if action == "respawn":
            self.player.respawn(self.spawn)
            self.mode = "playing"
            self._last_tick = time.perf_counter()
        elif action == "quit":
            self._shutdown(bpy.context)

    def _chat_event(self, event):
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        if event.type == "ESC":
            self.mode = "playing"
            return {"RUNNING_MODAL"}
        if event.type in {"RETURN", "NUMPAD_ENTER"}:
            text = self.chat_input.strip()
            self.mode = "playing"
            self.chat_input = ""
            if text:
                if text.startswith("/"):
                    self._run_command(text)
                else:
                    self.chat_msg("<玩家> " + text)
            return {"RUNNING_MODAL"}
        if event.type == "BACK_SPACE":
            prefix_len = len(self.chat_open_prefix)
            if len(self.chat_input) > prefix_len:
                self.chat_input = self.chat_input[:-1]
            return {"RUNNING_MODAL"}
        if event.unicode and event.unicode.isprintable():
            self.chat_input += event.unicode
        return {"RUNNING_MODAL"}

    def _inventory_event(self, event):
        cx, cy = self.ui.w / 2, self.ui.h / 2
        lay = inventory_layout(cx, cy, self.inv.creative)
        if event.type in {"ESC", "E"} and event.value == "PRESS":
            self.mode = "playing"
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            return {"RUNNING_MODAL"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            return {"RUNNING_MODAL"}
        if event.type in {"LEFTMOUSE", "RIGHTMOUSE"} and event.value == "PRESS":
            ux = self.mouse_px[0] / self.ui.scale
            uy = self.mouse_px[1] / self.ui.scale
            right = event.type == "RIGHTMOUSE"
            for rect, idx, kind in inventory_slot_rects(lay):
                if not point_in(rect, ux, uy):
                    continue
                if kind == "palette":
                    items = B.CREATIVE_ITEMS
                    k = idx - 9
                    if 0 <= k < len(items):
                        self.inv.cursor = Slot(items[k], 64)
                else:
                    self.inv.click_slot(idx, right)
                return {"RUNNING_MODAL"}
            # 点空白处：把手上的东西丢掉
            if not self.inv.cursor.empty:
                self.inv.cursor = Slot()
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    # ------------------------------------------------------------------
    # 逻辑帧
    # ------------------------------------------------------------------
    def _tick(self, context):
        now = time.perf_counter()
        dt = min(now - self._last_tick, 0.15)
        self._last_tick = now
        self.perf["ticks"] = self.perf.get("ticks", 0) + 1
        self._frame_times.append(dt)
        if len(self._frame_times) > 30:
            self._frame_times.pop(0)
        avg = sum(self._frame_times) / max(1, len(self._frame_times))
        self.fps = 1.0 / avg if avg > 1e-5 else 60.0

        if self.frozen:      # 性能诊断用：冻结一切更新，只留绘制
            return

        if self.mode == "loading":
            t0 = time.perf_counter()
            self._loading_step()
            self.perf["loading"] += time.perf_counter() - t0
            self.ui.set_region(self.region.width, self.region.height)
            return

        if self.mode == "warmup":
            # 这一阶段做三件事：
            # 1) 把渲染距离内的区块建完；
            # 2) 触发 Blender 的一次性"暖机"（第一次真正画这个场景要好几秒，
            #    期间视口是空的——用进度界面盖住）；
            # 3) 实测一次渲染耗时，等它降到 1 秒以内再让玩家上手。
            self._warmup_elapsed += dt
            for _ in range(6):
                if not self._build_one_dirty():
                    break
            self._update_camera()
            self._warmup_ready, self._warmup_need = self._area_progress()
            built = self._warmup_ready >= self._warmup_need
            if built and self._warmup_elapsed - self._gl_last > 0.6:
                self._gl_last = self._warmup_elapsed
                t0 = time.perf_counter()
                try:
                    with bpy.context.temp_override(window=self.window,
                                                   area=self.area,
                                                   region=self.region):
                        bpy.ops.render.opengl(write_still=False, view_context=True)
                except Exception:
                    pass
                self._gl_cost = time.perf_counter() - t0
                self._gl_tries += 1
            if (built and self._gl_tries >= 3 and self._warmup_elapsed > 3.0
                    and self._gl_cost < 1.0):
                self._start_playing()
            elif self._warmup_elapsed >= self._warmup_total:
                self._start_playing()
            return

        if self.mode == "playing":
            if self.player.dead:
                self.mode = "dead"
                self._release_all_keys()
            else:
                _t = time.perf_counter()
                self.player.update(self.world, dt, self.keys)
                self.perf["t_phys"] += time.perf_counter() - _t
                self._update_breaking(dt)
                self._update_place_repeat(dt)
                self.time_of_day = (self.time_of_day +
                                    dt / self.day_seconds) % 1.0

        _t = time.perf_counter()
        self._stream_chunks()
        self.perf["t_stream"] += time.perf_counter() - _t
        _t = time.perf_counter()
        self._update_target()
        self.perf["t_target"] += time.perf_counter() - _t
        _t = time.perf_counter()
        self._update_camera()
        self.perf["t_cam"] += time.perf_counter() - _t
        _t = time.perf_counter()
        self._update_sky(dt)
        self.perf["t_sky"] += time.perf_counter() - _t
        self.perf["t_tick"] += time.perf_counter() - now
        if self._item_name_timer > 0:
            self._item_name_timer -= dt
        for line in self.chat:
            line["age"] += dt
        self.chat = [c for c in self.chat if c["age"] < 12.0][-60:]

    # ---------------- 区块流式加载 ----------------
    def _build_one_dirty(self) -> bool:
        """在渲染距离内找一个脏区块重建网格；没有可建的就返回 False。"""
        if self.no_stream:
            return False
        px, pz = self.player.pos[0], self.player.pos[2]
        pcx = int(math.floor(px / CHUNK_X))
        pcz = int(math.floor(pz / CHUNK_Z))
        rd = self._rd
        for (dx, dz) in self._offsets:
            d2 = dx * dx + dz * dz
            if d2 > rd * rd:
                continue
            cx, cz = pcx + dx, pcz + dz
            if not self.world.has_chunk(cx, cz):
                self.world.get_chunk(cx, cz)
                return True
            ch = self.world.chunks[(cx, cz)]
            if ch.dirty:
                self._build_mesh(cx, cz)
                return True
        return False

    def _area_progress(self):
        """返回 (已建好的区块数, 需要建的总数)。"""
        px, pz = self.player.pos[0], self.player.pos[2]
        pcx = int(math.floor(px / CHUNK_X))
        pcz = int(math.floor(pz / CHUNK_Z))
        rd = self._rd
        ready = need = 0
        for (dx, dz) in self._offsets:
            if dx * dx + dz * dz > rd * rd:
                continue
            need += 1
            ch = self.world.chunks.get((pcx + dx, pcz + dz))
            if ch is not None and not ch.dirty:
                ready += 1
        return ready, need

    def _stream_chunks(self):
        if self.no_stream:
            return
        px, pz = self.player.pos[0], self.player.pos[2]
        pcx = int(math.floor(px / CHUNK_X))
        pcz = int(math.floor(pz / CHUNK_Z))
        rd = self._rd
        # 生成
        gen_budget = 3
        for (dx, dz) in self._offsets:
            if dx * dx + dz * dz > (rd + 1) ** 2:
                continue
            cx, cz = pcx + dx, pcz + dz
            if not self.world.has_chunk(cx, cz):
                self.world.get_chunk(cx, cz)
                gen_budget -= 1
                if gen_budget <= 0:
                    break
        # 建网格（时间预算）
        # 建网格：每个逻辑帧最多重建 1 个区块（重建很贵，交给下一帧继续）
        for (dx, dz) in self._offsets:
            d2 = dx * dx + dz * dz
            if d2 > rd * rd:
                continue
            cx, cz = pcx + dx, pcz + dz
            ch = self.world.chunks.get((cx, cz))
            if ch is not None and ch.dirty:
                self._build_mesh(cx, cz)
                break
        # 可见性 / 卸载：只在玩家跨到新区块时做一次
        if (pcx, pcz) != self._last_player_chunk:
            self._last_player_chunk = (pcx, pcz)
            self._update_chunk_visibility(pcx, pcz)

    def _rebuild_offsets(self):
        rd = self._rd
        self._offsets = sorted(
            [(dx, dz) for dx in range(-rd - 3, rd + 4)
             for dz in range(-rd - 3, rd + 4)],
            key=lambda o: o[0] * o[0] + o[1] * o[1])

    # ---------------- 目标 / 挖掘 / 放置 ----------------
    def _update_target(self):
        from .mc_raycast import look_vector
        eye = self.player.eye
        d = look_vector(self.player.yaw, self.player.pitch)
        hit = raycast(self.world, eye, d, 5.0)
        if hit is not None:
            self.target = hit
        else:
            self.target = None
            self.break_progress = 0.0

    def _break_time(self, blk) -> float:
        if blk.hardness < 0:
            return 1e9
        mult = 3.0 if blk.tool == "pickaxe" else 1.5
        return max(0.08, blk.hardness * mult)

    def _update_breaking(self, dt):
        if self.break_cooldown > 0:
            self.break_cooldown -= dt
        if not self.mouse_left or self.target is None:
            self.break_progress = 0.0
            self.break_pos = None
            return
        pos, normal, bid = self.target
        blk = B.BLOCKS[bid]
        if blk.unbreakable or bid == 0:
            self.break_progress = 0.0
            return
        if self.break_pos != pos:
            self.break_pos = pos
            self.break_progress = 0.0
        if self.player.creative:
            if self.break_cooldown <= 0:
                self._break_block(pos, blk)
                self.break_cooldown = 0.22
            return
        self.break_progress += dt / self._break_time(blk)
        if self.break_progress >= 1.0:
            self._break_block(pos, blk)
            self.break_progress = 0.0

    def _break_block(self, pos, blk):
        self.world.set_block(pos[0], pos[1], pos[2], 0)
        if not self.player.creative and blk.drop:
            drop = B.BY_NAME.get(blk.drop)
            if drop is not None and drop.id != 0:
                left = self.inv.add(drop.name, blk.drop_count)
                self._show_item_name(drop.label)
                if left:
                    self.chat_msg("背包已满")
        self.break_pos = None

    def _use_item(self):
        if self.target is None or self.place_cooldown > 0:
            return
        self.place_cooldown = 0.22
        if not self._place_block():
            # 没有可放置的方块时，右键退化为"使用/交互"
            pass

    def _update_place_repeat(self, dt):
        if self.place_cooldown > 0:
            self.place_cooldown -= dt
        if self.mouse_right and self.place_cooldown <= 0 and self.mode == "playing":
            if self._place_block():
                self.place_cooldown = 0.22

    def _place_block(self) -> bool:
        if self.target is None:
            return False
        pos, normal, bid = self.target
        name = self.inv.held_name()
        if not name:
            return False
        blk = B.BY_NAME.get(name)
        if blk is None or blk.id == 0:
            return False
        tx, ty, tz = pos[0] + normal[0], pos[1] + normal[1], pos[2] + normal[2]
        if not (0 <= ty < WORLD_H):
            return False
        exist = self.world.get_block(tx, ty, tz)
        if exist != 0 and not B.LIQUID_TABLE[exist]:
            return False
        if blk.solid and self._intersects_player(tx, ty, tz):
            return False
        if self.world.get_block(tx, ty, tz) == blk.id:
            return False
        self.world.set_block(tx, ty, tz, blk.id)
        self.inv.consume_held(1)
        if not self.inv.creative:
            self._show_item_name(blk.label)
        return True

    def _intersects_player(self, bx, by, bz) -> bool:
        px0, py0, pz0, px1, py1, pz1 = self.player.aabb
        return not (bx + 1 <= px0 or bx >= px1 or by + 1 <= py0 or by >= py1
                    or bz + 1 <= pz0 or bz >= pz1)

    def _pick_block(self):
        if self.target is None:
            return
        bid = self.target[2]
        blk = B.BLOCKS[bid]
        if blk.id == 0:
            return
        self.inv.slots[self.inv.selected] = Slot(blk.name, 64 if self.inv.creative else 1)
        self._show_item_name(blk.label)

    def _drop_item(self):
        s = self.inv.held()
        if s.empty or self.inv.creative:
            return
        s.count -= 1
        if s.count <= 0:
            s.name, s.count = None, 0

    def _toggle_gamemode(self):
        self.player.creative = not self.player.creative
        self.inv.creative = self.player.creative
        if self.player.creative:
            self.inv.fill_creative()
            self.player.flying = True
        else:
            self.inv.clear()
            self.player.flying = False
        self.chat_msg("游戏模式：" + ("创造" if self.player.creative else "生存"))

    def _show_item_name(self, label=None):
        name = label
        if name is None:
            s = self.inv.held()
            blk = B.BY_NAME.get(s.name) if s.name else None
            name = blk.label if blk else ""
        self._item_name = name
        self._item_name_timer = 2.2

    # ---------------- 相机 / 天空 ----------------
    def _update_camera(self):
        from .mc_raycast import view_matrix_axes
        p = self.player
        eye = p.eye.copy()               # (x, y=高度, z)
        eye[1] += p.bob
        if self.third_person:
            fwd, right, up = view_matrix_axes(p.yaw, p.pitch)
            eye = eye - fwd * 4.0 + up * 0.4
        # 世界约定 (x, y, z) -> Blender (X, Y, Z)：X=x, Y=z, Z=y
        loc = self.cam.location
        bx, by, bz = float(eye[0]), float(eye[2]), float(eye[1])
        if (abs(loc[0] - bx) + abs(loc[1] - by) + abs(loc[2] - bz)) > 1e-6:
            self.cam.location = (bx, by, bz)
        rot = (math.pi / 2 + p.pitch, 0.0, math.pi - p.yaw)
        er = self.cam.rotation_euler
        if (abs(er[0] - rot[0]) + abs(er[1] - rot[1])
                + abs(er[2] - rot[2]) > 1e-6):
            self.cam.rotation_euler = Euler(rot, "XYZ")
        target_fov = FOV * (1.12 if (p.sprinting and not p.flying) else 1.0)
        cur = math.degrees(self.cam.data.angle)
        if abs(cur - target_fov) > 0.05:
            self.cam.data.angle = math.radians(cur + (target_fov - cur) * 0.15)

    def _update_sky(self, dt=0.0):
        # 天空/太阳只在必要时重算：写这两处会触发整个场景重新求值
        self._sky_timer -= dt
        if self._sky_timer > 0.5 and self._sky_applied:
            return
        self._sky_timer = 0.5
        t = self.time_of_day
        # 0=清晨, 0.25=正午, 0.5=黄昏, 0.75=午夜
        day = (0.45, 0.62, 0.90)
        night = (0.02, 0.03, 0.08)
        dawn = (0.75, 0.50, 0.35)
        dusk = (0.85, 0.45, 0.28)

        def lerp(a, b, k):
            return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))

        if t < 0.08:
            c = lerp(night, dawn, t / 0.08)
        elif t < 0.16:
            c = lerp(dawn, day, (t - 0.08) / 0.08)
        elif t < 0.42:
            c = day
        elif t < 0.52:
            c = lerp(day, dusk, (t - 0.42) / 0.10)
        elif t < 0.60:
            c = lerp(dusk, night, (t - 0.52) / 0.08)
        elif t < 0.92:
            c = night
        else:
            c = lerp(night, dawn, (t - 0.92) / 0.08)
        if self._sky_color is not None and max(
                abs(c[i] - self._sky_color[i]) for i in range(3)) < 0.01:
            return
        self._sky_color = c
        self._sky_applied = True
        try:
            self.space.shading.background_color = c
            # 世界节点也一起改：MATERIAL 预览在 use_scene_world 打开时用的是世界背景
            world = self.scene.world
            if world is not None and world.node_tree is not None:
                for node in world.node_tree.nodes:
                    if node.type == "BACKGROUND":
                        node.inputs[0].default_value = (c[0], c[1], c[2], 1.0)
        except Exception:
            pass
        sun = bpy.data.objects.get("MC_Sun")
        if sun is not None:
            ang = (t - 0.25) * math.tau
            # 太阳保持较高角度（否则清晨/黄昏地形会黑成一片），用亮度体现昼夜
            sun.rotation_euler = (math.radians(42 + 12 * math.cos(ang)), 0.0,
                                  math.radians(30))
            brightness = max(0.0, min(1.0, 0.5 + 0.5 * math.cos(ang)))
            sun.data.energy = 0.9 + 2.9 * brightness

    # ---------------- 聊天 / 命令 ----------------
    def chat_msg(self, text):
        self.chat.append({"text": str(text), "age": 0.0})
        if len(self.chat) > 60:
            self.chat = self.chat[-60:]

    def _run_command(self, text):
        parts = text[1:].split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]
        p = self.player
        if cmd in ("help", "?"):
            self.chat_msg("/gamemode creative|survival  /time set day|night|<0-1>")
            self.chat_msg("/tp x y z   /give 方块 数量   /seed   /save   /load")
            self.chat_msg("/render 2-12   /fly   /kill   /spawn   /clear")
        elif cmd == "gamemode":
            want = (args[0].lower() if args else "")
            creative = want in ("creative", "c", "1") if want else not p.creative
            if creative != p.creative:
                self._toggle_gamemode()
            self.chat_msg("游戏模式：" + ("创造" if p.creative else "生存"))
        elif cmd == "time":
            if args and args[0] == "set":
                val = args[1].lower() if len(args) > 1 else "day"
                table = {"day": 0.05, "noon": 0.25, "sunset": 0.5,
                         "night": 0.75, "midnight": 0.75, "sunrise": 0.0}
                if val in table:
                    self.time_of_day = table[val]
                else:
                    try:
                        self.time_of_day = float(val) % 1.0
                    except ValueError:
                        pass
            hours = (self.time_of_day * 24 + 6) % 24
            self.chat_msg(f"时间：{int(hours):02d}:{int((hours % 1) * 60):02d}")
        elif cmd == "tp":
            try:
                p.pos[:] = (float(args[0]), float(args[1]), float(args[2]))
                p.vel[:] = 0
                self.chat_msg("已传送")
            except (IndexError, ValueError):
                self.chat_msg("用法：/tp x y z")
        elif cmd == "give":
            if not args:
                self.chat_msg("用法：/give 方块 [数量]")
                return
            blk = B.BY_NAME.get(args[0]) or B.BY_LABEL.get(args[0])
            if blk is None:
                self.chat_msg("没有这个方块：" + args[0])
                return
            count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 64
            left = self.inv.add(blk.name, count)
            self.chat_msg(f"已获得 {blk.label} x{count - left}")
        elif cmd == "seed":
            self.chat_msg(f"种子：{self.world.seed}")
        elif cmd == "save":
            self.chat_msg("已保存：" + mc_save.save_world(self.world, self.player, self.inv))
        elif cmd == "load":
            got = mc_save.load_world()
            if got is None:
                self.chat_msg("没有找到存档")
            else:
                self._adopt_world(*got)
                self.chat_msg("存档已载入")
        elif cmd == "render":
            try:
                self._rd = max(2, min(MAX_RENDER_DISTANCE, int(args[0])))
                self._rebuild_offsets()
            except (IndexError, ValueError):
                pass
            self.chat_msg(f"渲染距离 = {self._rd}")
        elif cmd == "fly":
            p.flying = not p.flying
            self.chat_msg("飞行：" + ("开" if p.flying else "关"))
        elif cmd == "kill":
            p.creative = False
            p.damage(999)
            self.chat_msg("你被自己杀死了")
        elif cmd == "spawn":
            p.pos[:] = self.spawn
            p.vel[:] = 0
            self.chat_msg("已回到出生点")
        elif cmd == "clear":
            self.inv.clear()
            self.chat_msg("背包已清空")
        else:
            self.chat_msg("未知命令：" + cmd)

    def _adopt_world(self, world, meta):
        """载入存档后重建场景。"""
        for (cx, cz) in list(self.world.chunks.keys()):
            mc_render.remove_chunk_object(cx, cz)
        self._obj_cache.clear()
        self._last_player_chunk = None
        self.world = world
        self.spawn = tuple(meta.get("pos", [0.5, 80.0, 0.5]))
        p = self.player
        p.pos = np.array(meta.get("pos", [0.5, 80.0, 0.5]), dtype=np.float64)
        p.vel[:] = 0.0
        p.yaw = float(meta.get("yaw", 0.0))
        p.pitch = float(meta.get("pitch", 0.0))
        p.health = float(meta.get("health", 20.0))
        p.creative = bool(meta.get("creative", True))
        p.flying = bool(meta.get("flying", False))
        self.inv.creative = p.creative
        self.inv.from_dict(meta.get("inventory"))
        p.dead = False

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def _draw_lines(self):
        """POST_VIEW：方块选中框。"""
        if getattr(self, "target", None) is None or self.mode not in ("playing", "chat"):
            return
        pos = self.target[0]
        x, y, z = pos                    # y = 高度
        e = 0.002
        x0, y0, z0 = x - e, y - e, z - e
        x1, y1, z1 = x + 1 + e, y + 1 + e, z + 1 + e
        # 转成 Blender 世界坐标（Z 向上）
        c = [(x0, z0, y0), (x1, z0, y0), (x1, z0, y1), (x0, z0, y1),
             (x0, z1, y0), (x1, z1, y0), (x1, z1, y1), (x0, z1, y1)]
        idx = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
               (0, 4), (1, 5), (2, 6), (3, 7)]
        verts = [c[i] for pair in idx for i in pair]
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINES", {"pos": verts})
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.blend_set("ALPHA")
        try:
            gpu.state.line_width_set(2.0)
        except Exception:
            pass
        shader.uniform_float("color", (0.0, 0.0, 0.0, 0.85))
        batch.draw(shader)
        gpu.state.line_width_set(1.0)

    def _draw_hud(self):
        ctx = bpy.context
        if ctx.region is None or ctx.space_data is None:
            return
        if ctx.space_data.type != "VIEW_3D":
            return
        if ctx.area is None or ctx.area.as_pointer() != self.area_ptr:
            return
        ui = self.ui
        if not ui.ready:
            ui.ensure(mc_render.ensure_atlas())
        ui.set_region(ctx.region.width, ctx.region.height)
        ui.begin()
        try:
            self._compose_hud(ui)
        except Exception as exc:      # 绘制出错不要中断游戏
            DRAW_ERRORS.append(f"{type(exc).__name__}: {exc}")
            ui.text(f"HUD 错误: {exc}", 8, 8, 8, (1, 0.4, 0.4, 1))
        ui.end()

    def _compose_hud(self, ui):
        cx, cy = ui.w / 2.0, ui.h / 2.0
        p = self.player
        if self.mode == "loading":
            self._loading_screen(ui)
            return
        if self.mode == "warmup":
            self._warmup_screen(ui)
            return
        if self.hud_visible:
            if self.mode in ("playing", "chat"):
                ui.crosshair(cx, cy)
                self._crack_overlay(ui)
                if not p.creative and 0 < self.break_progress < 1.0:
                    w = 60.0
                    ui.rect(cx - w / 2, cy - 22, w, 4, (0, 0, 0, 0.6))
                    ui.rect(cx - w / 2 + 1, cy - 21, (w - 2) * self.break_progress, 2,
                            (0.9, 0.9, 0.9, 0.9))
            x0, bottom, slot, _ = hotbar_layout(cx)
            ui.hotbar(self.inv, cx)
            # 生命 / 饥饿
            hy = bottom + slot + 12
            ui.health(p.health, x0 + 1, hy)
            ui.hunger_bar(p.hunger, x0 + 9 * slot + 1, hy)
            if p.head_in_water:
                ui.bubbles(p.air / max(0.001, p.max_air), x0 + 1, hy + 12)
            # 经验条
            ui.xp_bar(cx, bottom + slot + 4, 9 * slot + 2,
                      p.xp % 1.0 if p.xp else 0.0, p.level)
            # 物品名
            if self._item_name_timer > 0 and self._item_name:
                ui.item_name(self._item_name, cx, bottom + slot + 24)
            self._draw_chat(ui)
            if self.debug:
                self._draw_debug(ui)
        if self.mode == "inventory":
            self._draw_inventory(ui)
        elif self.mode == "pause":
            self._draw_pause(ui)
        elif self.mode == "dead":
            self._draw_death(ui)

    # ---------------- 各界面 ----------------
    def _loading_screen(self, ui):
        cx, cy = ui.w / 2, ui.h / 2
        ui.dim(0.85)
        ui.text("正在生成世界 ...", cx, cy + 14, 16, (1, 1, 1, 1), True, "center")
        w = 200.0
        ratio = self._loading_done / max(1, self._loading_total)
        ui.rect(cx - w / 2, cy - 4, w, 8, (0, 0, 0, 0.8))
        ui.rect(cx - w / 2 + 1, cy - 3, (w - 2) * ratio, 6, (0.35, 0.75, 0.25, 1))
        ui.text(f"{int(ratio * 100)}%", cx, cy - 18, 9, (0.9, 0.9, 0.9, 1), True, "center")

    def _warmup_screen(self, ui):
        """把"建网格 + 编译着色器"这段等待藏在一个进度界面后面。"""
        cx, cy = ui.w / 2, ui.h / 2
        ui.dim(0.92)
        ui.text("正在准备渲染 ...", cx, cy + 20, 16, (1, 1, 1, 1), True, "center")
        ui.text("Blender 要为方块材质编译着色器，并上传区块网格",
                cx, cy + 4, 9, (0.85, 0.85, 0.85, 1), True, "center")
        ui.text("首次进入要等几秒到十几秒，之后就流畅了",
                cx, cy - 6, 9, (0.85, 0.85, 0.85, 1), True, "center")
        w = 200.0
        ratio = (self._warmup_ready / max(1, self._warmup_need)
                 if self._warmup_need else 0.0)
        ui.rect(cx - w / 2, cy - 24, w, 8, (0, 0, 0, 0.8))
        ui.rect(cx - w / 2 + 1, cy - 23, (w - 2) * ratio, 6, (0.35, 0.75, 0.25, 1))
        info = f"区块 {self._warmup_ready}/{self._warmup_need}"
        if self._gl_tries:
            info += f"   上次渲染耗时 {self._gl_cost:.1f}s"
        ui.text(info, cx, cy - 36, 9, (0.9, 0.9, 0.9, 1), True, "center")

    def _crack_overlay(self, ui):
        if self.break_progress <= 0.01 or self.target is None:
            return
        tile = TILE_INDEX[f"crack_{min(3, int(self.break_progress * 4))}"]
        rect = self._block_screen_rect(self.target[0])
        if rect is None:
            return
        x0, y0, x1, y1 = rect
        ui.crack_overlay(tile, x0, y0, x1, y1, 0.9)

    def _block_screen_rect(self, pos):
        """把方块投影到屏幕像素矩形（用于挖掘裂纹）。"""
        try:
            from mathutils import Vector
            deps = bpy.context.evaluated_depsgraph_get()
            w, h = self.region.width, self.region.height
            mat = self.cam.calc_matrix_camera(deps, x=w, y=h)
            inv = (mat @ self.cam.matrix_world.inverted())
            xs, ys = [], []
            for dx in (0, 1):
                for dy in (0, 1):
                    for dz in (0, 1):
                        # 世界约定 (x, y=高度, z) -> Blender (X, Y, Z)
                        v = Vector((pos[0] + dx, pos[2] + dz, pos[1] + dy))
                        p = inv @ v
                        if p.w <= 0.0001:
                            return None
                        ndc = p.xyz / p.w
                        xs.append((ndc.x * 0.5 + 0.5) * w)
                        ys.append((ndc.y * 0.5 + 0.5) * h)
            return (min(xs), min(ys), max(xs), max(ys))
        except Exception:
            return None

    def _draw_chat(self, ui):
        y = 34.0
        shown = [c for c in self.chat if c["age"] < 10.0][-10:]
        for line in reversed(shown):
            alpha = 1.0 if line["age"] < 8.0 else max(0.0, 1.0 - (line["age"] - 8.0) / 2.0)
            ui.text(line["text"], 4, y, 8, (1, 1, 1, alpha), True)
            y += 10
        if self.mode == "chat":
            ui.rect(2, 2, ui.w - 4, 12, (0, 0, 0, 0.55))
            ui.text(self.chat_input + "_", 4, 5, 8, (1, 1, 1, 1), True)

    def _draw_debug(self, ui):
        p = self.player
        lines = [
            f"Blender Minecraft  |  FPS {self.fps:5.1f}",
            f"XYZ {p.pos[0]:8.2f} / {p.pos[1]:7.2f} / {p.pos[2]:8.2f}",
            f"区块 {int(p.pos[0] // 16)}, {int(p.pos[2] // 16)}   已加载 {len(self.world.chunks)}",
            f"朝向 {_facing_name(math.degrees(p.yaw))}  yaw={math.degrees(p.yaw):6.1f} "
            f"pitch={math.degrees(p.pitch):6.1f}",
            f"时间 {int((self.time_of_day * 24 + 6) % 24):02d}:"
            f"{int(((self.time_of_day * 24 + 6) % 1) * 60):02d}   种子 {self.world.seed}",
            f"模式 {'创造' if p.creative else '生存'}"
            f"{'  飞行' if p.flying else ''}{'  游泳' if p.in_water else ''}",
            f"渲染距离 {self._rd} 区块",
        ]
        if self.target is not None:
            pos, normal, bid = self.target
            blk = B.BLOCKS[bid]
            lines.append(f"看着 {blk.label} ({pos[0]}, {pos[1]}, {pos[2]}) "
                         f"硬度 {blk.hardness}")
        y = ui.h - 12
        for line in lines:
            w = ui.text_width(line, 8)
            ui.rect(3, y - 2, w + 4, 10, (0, 0, 0, 0.45))
            ui.text(line, 5, y, 8, (1, 1, 1, 1), True)
            y -= 11

    def _draw_inventory(self, ui):
        ui.dim(0.55)
        cx, cy = ui.w / 2, ui.h / 2
        lay = inventory_layout(cx, cy, self.inv.creative)
        px, py, pw, ph = lay["panel"]
        ui.panel(px, py, pw, ph)
        ui.text("创造模式物品栏" if self.inv.creative else "物品栏",
                px + 8, lay["title_y"], 9, (0.24, 0.24, 0.24, 1), False)
        ux, uy = self.mouse_px[0] / ui.scale, self.mouse_px[1] / ui.scale
        hover = None
        for rect, idx, kind in inventory_slot_rects(lay):
            x, y, s, _ = rect
            ui.inv_slot(x, y, s, hover=point_in(rect, ux, uy))
            if point_in(rect, ux, uy):
                hover = (rect, idx, kind)
            stack = None
            if kind == "hotbar":
                stack = self.inv.slots[idx]
            elif kind == "storage":
                stack = self.inv.slots[idx]
            elif kind == "palette":
                k = idx - 9
                if 0 <= k < len(B.CREATIVE_ITEMS):
                    stack = Slot(B.CREATIVE_ITEMS[k], 64)
            if stack is not None:
                ui.slot_icon(stack, x, y, s, self.inv.creative)
        # 提示
        if hover is not None:
            rect, idx, kind = hover
            name = None
            if kind in ("hotbar", "storage"):
                name = self.inv.slots[idx].name
            else:
                k = idx - 9
                if 0 <= k < len(B.CREATIVE_ITEMS):
                    name = B.CREATIVE_ITEMS[k]
            if name:
                blk = B.BY_NAME.get(name)
                if blk:
                    lines = [blk.label]
                    if blk.hardness >= 0:
                        lines.append(f"硬度 {blk.hardness:g}")
                    lines.append(f"id: {blk.name}")
                    tx = rect[0] + rect[2] + 6
                    ty = rect[1] + rect[3]
                    if tx + 90 > ui.w:
                        tx = rect[0] - 96
                    ui.tooltip(lines, tx, ty)
        # 鼠标手上的东西
        if not self.inv.cursor.empty:
            ui.slot_icon(self.inv.cursor, ux - 8, uy - 8, 16, False)
        ui.text("Esc/E 关闭   左键拿取   右键分一半", px + 8, py + ph - 24, 8,
                (0.28, 0.28, 0.28, 1), False)

    def _draw_pause(self, ui):
        ui.dim(0.66)
        cx, cy = ui.w / 2, ui.h / 2
        ui.text("游戏已暂停", cx, cy + 78, 16, (1, 1, 1, 1), True, "center")
        ux, uy = self.mouse_px[0] / ui.scale, self.mouse_px[1] / ui.scale
        for label, rect, action in pause_layout(cx, cy, self._rd):
            ui.button(label, rect[0], rect[1], rect[2], rect[3],
                      hover=point_in(rect, ux, uy))
        ui.text(f"种子 {self.world.seed}   方块 {len(self.world.chunks)} 区块",
                cx, cy - 78, 8, (0.85, 0.85, 0.85, 1), True, "center")

    def _draw_death(self, ui):
        ui.dim(0.0)
        ui.rect(0, 0, ui.w, ui.h, (0.35, 0.0, 0.0, 0.55))
        cx, cy = ui.w / 2, ui.h / 2
        ui.text("你死了！", cx, cy + 40, 24, (1, 1, 1, 1), True, "center")
        ui.text(f"种子 {self.world.seed}", cx, cy + 18, 9, (0.9, 0.9, 0.9, 1), True,
                "center")
        ux, uy = self.mouse_px[0] / ui.scale, self.mouse_px[1] / ui.scale
        for label, rect, action in death_layout(cx, cy):
            ui.button(label, rect[0], rect[1], rect[2], rect[3],
                      hover=point_in(rect, ux, uy))

    # ------------------------------------------------------------------
    # 结束
    # ------------------------------------------------------------------
    def _shutdown(self, context):
        try:
            if getattr(self, "_timer", None) is not None:
                context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        for handle, region in ((getattr(self, "_hud_handle", None), "WINDOW"),
                               (getattr(self, "_line_handle", None), "WINDOW")):
            if handle is not None:
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(handle, region)
                except Exception:
                    pass
        self._hud_handle = None
        self._line_handle = None
        try:
            mc_render.clear_world_objects()
        except Exception:
            pass
        self._restore_view_state()
        for w in list(bpy.data.worlds):
            if w.name == "MC_World":
                try:
                    bpy.data.worlds.remove(w)
                except Exception:
                    pass
        if _ACTIVE_INSTANCE and _ACTIVE_INSTANCE[0] is self:
            _ACTIVE_INSTANCE.clear()
        self.report({"INFO"}, "已退出《我的世界》")
        return {"CANCELLED"}

    def cancel(self, context):
        self._shutdown(context)


def mc_mesher_build(world, chunk):
    from . import mc_mesher
    return mc_mesher.build_chunk_data(world, chunk)
