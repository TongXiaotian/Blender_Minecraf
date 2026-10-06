"""Blender Minecraft —— 在 Blender 里运行的《我的世界》风格体素沙盒。

安装：编辑 → 偏好设置 → 插件 → 从磁盘安装 → 选这个文件夹里的 __init__.py
      （或把整个 blender_minecraft 文件夹打包成 zip 安装）
使用：3D 视图右上角 N 面板 → "Minecraft" 标签 → 开始游戏
      或者在 3D 视图里按 Shift+M

作者：DeepSeek Harness
"""
from __future__ import annotations

import bpy

from . import mc_game
from .mc_const import DEFAULT_RENDER_DISTANCE, MAX_RENDER_DISTANCE

bl_info = {
    "name": "Blender Minecraft (我的世界)",
    "author": "DeepSeek Harness",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D 视图 → 侧栏(N) → Minecraft / 菜单 View → 开始我的世界 / Shift+M",
    "description": "用 Blender Python 实现的《我的世界》风格体素沙盒：程序化地形、挖掘放置、"
                   "第一人称物理、物品栏/HUD 界面、昼夜、存档",
    "category": "Game",
    "doc_url": "",
    "tracker_url": "",
}

_addon_keymaps: list = []


class MC_Settings(bpy.types.PropertyGroup):
    seed: bpy.props.IntProperty(
        name="世界种子", description="0 = 每次随机", default=0, min=0)
    render_distance: bpy.props.IntProperty(
        name="渲染距离", description="以玩家为中心加载的区块半径",
        default=DEFAULT_RENDER_DISTANCE, min=2, max=MAX_RENDER_DISTANCE)
    creative: bpy.props.BoolProperty(
        name="创造模式", description="无限方块、瞬间破坏、可飞行", default=True)
    quality: bpy.props.EnumProperty(
        name="画质", default="medium",
        items=[("high", "高（阴影 + TAA4）", "最好看，最吃显卡"),
               ("medium", "中（阴影 + TAA1）", "推荐"),
               ("low", "低（关闭阴影）", "核显推荐，最流畅")])
    hide_other_objects: bpy.props.BoolProperty(
        name="隐藏场景其它物体", default=True)


class MC_OT_play(bpy.types.Operator):
    """开始游戏（读取侧栏设置）。"""

    bl_idname = "mc_blender.play_panel"
    bl_label = "开始我的世界"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = getattr(context.scene, "mc_settings", None)
        op = mc_game.MC_Game
        props = {}
        if st is not None:
            props = {"seed": st.seed, "render_distance": st.render_distance,
                     "creative": st.creative, "quality": st.quality}
        try:
            bpy.ops.mc_blender.play("INVOKE_DEFAULT", **props)
        except Exception as exc:
            self.report({"ERROR"}, f"启动失败：{exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class MC_PT_main(bpy.types.Panel):
    bl_label = "我的世界"
    bl_idname = "MC_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Minecraft"

    def draw(self, context):
        layout = self.layout
        st = getattr(context.scene, "mc_settings", None)
        if st is None:
            layout.label(text="设置未初始化", icon="ERROR")
            return
        col = layout.column(align=True)
        col.prop(st, "seed")
        col.prop(st, "render_distance")
        col.prop(st, "quality")
        col.prop(st, "creative")
        col.separator()
        row = layout.row(align=True)
        row.scale_y = 1.6
        row.operator(MC_OT_play.bl_idname, icon="PLAY", text="开始游戏")
        box = layout.box()
        box.label(text="操作：", icon="INFO")
        for line in ("WASD 移动 / 空格跳跃", "左键挖掘 / 右键放置",
                     "鼠标中键取方块", "E 物品栏  T 聊天  Esc 菜单",
                     "F3 调试  F5 第三人称  F1 隐藏界面",
                     "创造模式双击空格开关飞行"):
            box.label(text=line)


def _menu_func(self, context):
    self.layout.separator()
    self.layout.operator(MC_OT_play.bl_idname, icon="PLAY",
                         text="开始我的世界")


def register():
    bpy.utils.register_class(MC_Settings)
    bpy.utils.register_class(mc_game.MC_Game)
    bpy.utils.register_class(MC_OT_play)
    bpy.utils.register_class(MC_PT_main)
    bpy.types.Scene.mc_settings = bpy.props.PointerProperty(type=MC_Settings)
    bpy.types.VIEW3D_MT_view.append(_menu_func)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm else None
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        kmi = km.keymap_items.new(MC_OT_play.bl_idname, "M", "PRESS", shift=True)
        _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()
    try:
        bpy.types.VIEW3D_MT_view.remove(_menu_func)
    except Exception:
        pass
    try:
        del bpy.types.Scene.mc_settings
    except Exception:
        pass
    for cls in (MC_PT_main, MC_OT_play, mc_game.MC_Game, MC_Settings):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
