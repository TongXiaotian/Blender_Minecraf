"""安装路径测试：把 zip 当插件安装、启用，并确认注册成功。

用法（后台）：
    set BLENDER_USER_SCRIPTS=<可写目录>
    blender --background --factory-startup --python tools/install_test.py -- <zip路径>
"""
from __future__ import annotations

import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ZIP = argv[0] if argv else os.path.join(ROOT, "blender_minecraft.zip")

print("=" * 60)
print("Blender", bpy.app.version_string)
print("用户脚本目录:", bpy.utils.script_path_user())
print("插件 zip:", ZIP, os.path.exists(ZIP))

try:
    bpy.ops.preferences.addon_install(filepath=ZIP, overwrite=True)
    print("[OK] addon_install 成功")
except Exception as exc:
    print(f"[!!] addon_install 失败: {type(exc).__name__}: {exc}")
    sys.exit(1)

try:
    bpy.ops.preferences.addon_enable(module="blender_minecraft")
    print("[OK] addon_enable 成功")
except Exception as exc:
    print(f"[!!] addon_enable 失败: {type(exc).__name__}: {exc}")
    sys.exit(1)

import blender_minecraft as pkg               # noqa: E402
print("模块位置:", pkg.__file__)
print("bl_info:", pkg.bl_info["name"], pkg.bl_info["version"])

checks = [
    ("Scene.mc_settings 已注册", hasattr(bpy.types.Scene, "mc_settings")),
    ("面板 MC_PT_main 存在", hasattr(bpy.types, "MC_PT_main")),
    ("操作符 mc_blender.play 存在", hasattr(bpy.types, "MC_BLENDER_OT_play")),
    ("面板操作符存在", hasattr(bpy.types, "MC_BLENDER_OT_play_panel")),
]
ok = True
for name, cond in checks:
    print(("  [OK] " if cond else "  [!!] ") + name)
    ok = ok and cond

# 默认设置
st = bpy.context.scene.mc_settings
print(f"默认设置：种子={st.seed} 渲染距离={st.render_distance} "
      f"画质={st.quality} 创造={st.creative}")

# 卸载再启用（验证 unregister 也干净）
try:
    bpy.ops.preferences.addon_disable(module="blender_minecraft")
    bpy.ops.preferences.addon_enable(module="blender_minecraft")
    print("[OK] 禁用/重新启用正常（unregister/register 都没报错）")
except Exception as exc:
    print(f"[!!] 重新启用失败: {type(exc).__name__}: {exc}")
    ok = False

print("=" * 60)
print("全部通过 ✅" if ok else "有失败项 ❌")
print("=" * 60)
