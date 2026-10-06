"""玩家：移动、碰撞、跳跃、游泳、飞行、生命值/摔落伤害。

坐标约定与 Minecraft 一致：(x, y, z)，其中 **y 是高度**，z 是水平轴之一。
（注意 Blender 世界坐标是 z 向上，所以在交给相机/绘制时要做一次轴交换。）
数值尽量对齐原版：重力 32 m/s²、行走 4.317、疾跑 5.612、跳跃初速 8.95（约 1.25 格）。
"""
from __future__ import annotations

import math

import numpy as np

from . import mc_blocks as B
from .mc_const import (FLY_SPEED, GRAVITY, JUMP_SPEED, PLAYER_EYE,
                       PLAYER_HEIGHT, PLAYER_WIDTH, SNEAK_SPEED,
                       SPRINT_SPEED, TERMINAL_VELOCITY, WALK_SPEED)

HALF = PLAYER_WIDTH / 2.0
EPS = 1e-4


class Player:
    def __init__(self, spawn=(0.5, 90.0, 0.5), creative=True):
        self.pos = np.array(spawn, dtype=np.float64)   # (x, y=高度, z)
        self.vel = np.zeros(3, dtype=np.float64)
        self.yaw = 0.0
        self.pitch = 0.0
        self.on_ground = False
        self.in_water = False
        self.head_in_water = False
        self.flying = False
        self.sprinting = False
        self.sneaking = False
        self.creative = creative
        # 状态
        self.health = 20.0
        self.max_health = 20.0
        self.hunger = 20.0
        self.air = 15.0                # 秒
        self.max_air = 15.0
        self.xp = 0.0
        self.level = 0
        self.dead = False
        self._fall_from = None
        self._regen_timer = 0.0
        self.bob = 0.0                 # 走路摆动（用于相机）
        self._step_dist = 0.0

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------
    @property
    def eye(self):
        """眼睛位置（世界约定：y 是高度）。"""
        return self.pos + np.array((0.0, PLAYER_EYE, 0.0), dtype=np.float64)

    @property
    def aabb(self):
        """(x0, y0, z0, x1, y1, z1)，y 是高度。"""
        return (self.pos[0] - HALF, self.pos[1], self.pos[2] - HALF,
                self.pos[0] + HALF, self.pos[1] + PLAYER_HEIGHT, self.pos[2] + HALF)

    # ------------------------------------------------------------------
    # 碰撞
    # ------------------------------------------------------------------
    def _collides(self, world) -> bool:
        p = self.pos
        x0 = math.floor(p[0] - HALF + EPS)
        x1 = math.floor(p[0] + HALF - EPS)
        y0 = math.floor(p[1] + EPS)                       # y = 高度
        y1 = math.floor(p[1] + PLAYER_HEIGHT - EPS)
        z0 = math.floor(p[2] - HALF + EPS)
        z1 = math.floor(p[2] + HALF - EPS)
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                # 区块还没加载时视为实心，免得玩家掉出世界
                if not world.is_loaded(x, z):
                    return True
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    if B.SOLID_TABLE[world.get_block(x, y, z)]:
                        return True
        return False

    def _would_collide(self, world, pos) -> bool:
        old = self.pos
        self.pos = np.asarray(pos, dtype=np.float64)
        try:
            return self._collides(world)
        finally:
            self.pos = old

    # ------------------------------------------------------------------
    # 主更新
    # ------------------------------------------------------------------
    def update(self, world, dt: float, keys: set):
        if self.dead:
            self.vel[:] = 0.0
            return
        dt = min(dt, 0.05)
        steps = max(1, int(math.ceil(dt / (1.0 / 120.0))))
        sub = dt / steps
        for _ in range(steps):
            self._step(world, sub, keys)

    def _step(self, world, dt: float, keys: set):
        # ---- 环境检测 ----
        feet_block = world.get_block(math.floor(self.pos[0]),
                                     math.floor(self.pos[1] + 0.1),
                                     math.floor(self.pos[2]))
        eye = self.eye
        eye_block = world.get_block(math.floor(eye[0]), math.floor(eye[1]),
                                    math.floor(eye[2]))
        self.in_water = bool(B.LIQUID_TABLE[feet_block])
        self.head_in_water = bool(B.LIQUID_TABLE[eye_block])
        if self.in_water:
            if not self.creative:
                self.flying = False
            self._fall_from = None

        # ---- 输入方向（水平：前 = (-sin yaw, -cos yaw)，右 = (cos yaw, -sin yaw)）----
        f = (1.0 if "forward" in keys else 0.0) - (1.0 if "back" in keys else 0.0)
        r = (1.0 if "right" in keys else 0.0) - (1.0 if "left" in keys else 0.0)
        sy, cy = math.sin(self.yaw), math.cos(self.yaw)
        fx, fz = -sy, -cy
        rx, rz = cy, -sy
        dx, dz = fx * f + rx * r, fz * f + rz * r
        mag = math.hypot(dx, dz)
        if mag > 1e-6:
            dx, dz = dx / mag, dz / mag

        self.sneaking = "sneak" in keys and not self.flying
        self.sprinting = ("sprint" in keys and f > 0 and not self.sneaking
                          and not self.in_water)

        # ---- 目标速度 ----
        if self.flying:
            speed = FLY_SPEED * (1.8 if self.sprinting else 1.0)
        elif self.in_water:
            speed = 2.6
        elif self.sneaking:
            speed = SNEAK_SPEED
        elif self.sprinting:
            speed = SPRINT_SPEED
        else:
            speed = WALK_SPEED
        tx, tz = dx * speed, dz * speed

        # ---- 水平速度：地面加速快、空中控制弱 ----
        accel = 14.0 if (self.on_ground or self.flying) else 3.2
        if self.in_water:
            accel = 8.0
        k = min(1.0, accel * dt)
        self.vel[0] += (tx - self.vel[0]) * k
        self.vel[2] += (tz - self.vel[2]) * k

        # ---- 垂直（vel[1]）----
        if self.flying:
            if "sneak" in keys:
                self.vel[1] = -FLY_SPEED * 0.8
            elif "jump" in keys:
                self.vel[1] = FLY_SPEED * 0.8
            else:
                self.vel[1] *= max(0.0, 1.0 - 10.0 * dt)
        elif self.in_water:
            self.vel[1] -= GRAVITY * 0.22 * dt
            self.vel[1] = max(self.vel[1], -3.0)
            if "jump" in keys:
                self.vel[1] = 3.0
        else:
            self.vel[1] -= GRAVITY * dt
            if self.vel[1] < -TERMINAL_VELOCITY:
                self.vel[1] = -TERMINAL_VELOCITY
            if "jump" in keys and self.on_ground:
                self.vel[1] = JUMP_SPEED
                self.on_ground = False
                if self._fall_from is None:
                    self._fall_from = self.pos[1]

        # ---- 位移 + 碰撞 ----
        self._move(world, self.vel * dt)

        # ---- 记录下落起点 ----
        if self.vel[1] < -0.1 and not self.on_ground and self._fall_from is None:
            self._fall_from = self.pos[1] + 0.1

        # ---- 憋气 ----
        if self.head_in_water and not self.creative:
            self.air -= dt
            if self.air <= 0:
                self.air = 0.0
                self.damage(20.0 * dt)
        else:
            self.air = min(self.max_air, self.air + dt * 4.0)

        # ---- 缓慢回血 ----
        if not self.creative and 0 < self.health < self.max_health and self.hunger > 16:
            self._regen_timer += dt
            if self._regen_timer > 4.0:
                self._regen_timer = 0.0
                self.health = min(self.max_health, self.health + 1.0)

    # ------------------------------------------------------------------
    def _move(self, world, delta):
        # 垂直（轴 1 = 高度）
        if abs(delta[1]) > 1e-9:
            self.pos[1] += delta[1]
            if self._collides(world):
                if delta[1] < 0:
                    self.pos[1] = math.floor(self.pos[1]) + 1.0
                    self.vel[1] = 0.0
                    self.on_ground = True
                    if self._fall_from is not None and not self.creative:
                        dist = self._fall_from - self.pos[1]
                        if dist > 3.0:
                            self.damage(math.floor(dist - 3.0))
                    self._fall_from = None
                else:
                    self.pos[1] = (math.floor(self.pos[1] + PLAYER_HEIGHT)
                                   - PLAYER_HEIGHT - EPS)
                    self.vel[1] = 0.0
                if self._collides(world):
                    self.pos[1] -= delta[1]
                    self.vel[1] = 0.0
            elif delta[1] < 0:
                self.on_ground = False
        # 水平（轴 0 = x，轴 2 = z）
        for axis in (0, 2):
            d = delta[axis]
            if abs(d) < 1e-9:
                continue
            before = self.pos[axis]
            if self.sneaking and self.on_ground and not self.flying and not self.in_water:
                # 潜行时不会走出方块边缘
                probe = self.pos.copy()
                probe[axis] += d
                probe[1] -= 0.6
                if not self._would_collide(world, probe) and probe[1] >= 0:
                    continue
            self.pos[axis] += d
            if self._collides(world):
                if d > 0:
                    self.pos[axis] = math.floor(self.pos[axis] + HALF) - HALF - EPS
                else:
                    self.pos[axis] = math.floor(self.pos[axis] - HALF) + 1.0 + HALF + EPS
                if self._collides(world):
                    self.pos[axis] = before
                self.vel[axis] = 0.0

        # 走路摆动
        horiz = math.hypot(self.vel[0], self.vel[2])
        if self.on_ground and horiz > 0.1:
            self._step_dist += horiz * 0.05
            self.bob = math.sin(self._step_dist * 2.2) * 0.055

    # ------------------------------------------------------------------
    def damage(self, amount: float):
        if self.creative or amount <= 0 or self.dead:
            return
        self.health -= amount
        if self.health <= 0:
            self.health = 0.0
            self.dead = True

    def heal(self, amount: float):
        self.health = min(self.max_health, self.health + amount)

    def respawn(self, spawn):
        self.pos = np.array(spawn, dtype=np.float64)
        self.vel[:] = 0.0
        self.health = self.max_health
        self.hunger = 20.0
        self.air = self.max_air
        self.dead = False
        self.on_ground = False
        self.flying = False
        self._fall_from = None
