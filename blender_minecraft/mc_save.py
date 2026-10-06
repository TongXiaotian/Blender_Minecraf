"""存档：把区块数据和玩家状态打包成一个 .npz 文件。"""
from __future__ import annotations

import json
import os

import bpy
import numpy as np


def save_dir() -> str:
    """存档目录：依次尝试 .blend 旁边 → 用户主目录 → 临时目录，取第一个可写的。"""
    import tempfile

    candidates = []
    if bpy.data.filepath:
        candidates.append(os.path.join(os.path.dirname(bpy.data.filepath), "MC_Saves"))
    candidates.append(os.path.join(os.path.expanduser("~"), "MC_Saves"))
    candidates.append(os.path.join(tempfile.gettempdir(), "MC_Saves"))
    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            probe = os.path.join(folder, ".write_test")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            return folder
        except OSError:
            continue
    return tempfile.gettempdir()


def world_path(name="world") -> str:
    return os.path.join(save_dir(), f"{name}.mcworld.npz")


def save_world(world, player, inv, name="world") -> str:
    path = world_path(name)
    arrays = {}
    for (cx, cz), ch in world.chunks.items():
        arrays[f"c_{cx}_{cz}"] = ch.blocks
    meta = {
        "seed": int(world.seed),
        "pos": [float(v) for v in player.pos],
        "vel": [float(v) for v in player.vel],
        "yaw": float(player.yaw),
        "pitch": float(player.pitch),
        "health": float(player.health),
        "hunger": float(player.hunger),
        "creative": bool(player.creative),
        "flying": bool(player.flying),
        "inventory": inv.to_dict(),
    }
    arrays["meta"] = np.array(json.dumps(meta))
    np.savez_compressed(path, **arrays)
    return path


def load_world(name="world"):
    """返回 (world, meta) 或 None。"""
    from . import mc_world

    path = world_path(name)
    if not os.path.exists(path):
        return None
    data = np.load(path, allow_pickle=False)
    meta = json.loads(str(data["meta"]))
    world = mc_world.World(seed=int(meta.get("seed", 20240501)))
    for key in data.files:
        if not key.startswith("c_"):
            continue
        _, cx, cz = key.split("_")
        ch = mc_world.Chunk(int(cx), int(cz))
        ch.blocks = data[key].astype(np.uint8).copy()
        ch.populated = True
        ch.dirty = True
        world.chunks[(int(cx), int(cz))] = ch
    return world, meta


def has_save(name="world") -> bool:
    return os.path.exists(world_path(name))
