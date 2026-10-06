"""物品栏 / 背包（原版 36 格：快捷栏 9 格 + 背包 27 格）。"""
from __future__ import annotations

from . import mc_blocks as B

SLOTS = 36
HOTBAR = 9


class Slot:
    __slots__ = ("name", "count")

    def __init__(self, name=None, count=0):
        self.name = name
        self.count = count

    @property
    def empty(self):
        return self.name is None or self.count <= 0

    def copy(self):
        return Slot(self.name, self.count)

    def __repr__(self):
        return f"<{self.name} x{self.count}>"


class Inventory:
    def __init__(self, creative=True):
        self.slots = [Slot() for _ in range(SLOTS)]
        self.selected = 0
        self.creative = creative
        self.cursor = Slot()          # 鼠标手里拿着的那一堆

    # ---------- 快捷栏 ----------
    def held(self) -> Slot:
        return self.slots[self.selected]

    def held_name(self):
        return self.slots[self.selected].name

    def select(self, index):
        self.selected = index % HOTBAR

    def scroll(self, delta):
        self.selected = (self.selected + delta) % HOTBAR

    # ---------- 增删 ----------
    def add(self, name, count=1, max_stack=64):
        """返回没能放下的数量。"""
        if not name or count <= 0:
            return 0
        # 先叠加到已有堆
        for s in self.slots:
            if s.name == name and s.count < max_stack:
                put = min(max_stack - s.count, count)
                s.count += put
                count -= put
                if count <= 0:
                    return 0
        # 再找空位
        for s in self.slots:
            if s.empty:
                put = min(max_stack, count)
                s.name = name
                s.count = put
                count -= put
                if count <= 0:
                    return 0
        return count

    def count_of(self, name=None) -> int:
        if name is None:
            return 0
        return sum(s.count for s in self.slots if s.name == name)

    def consume_held(self, count=1):
        if self.creative:
            return True
        s = self.held()
        if s.empty or s.count < count:
            return False
        s.count -= count
        if s.count <= 0:
            s.name, s.count = None, 0
        return True

    def take_held_all(self):
        s = self.held()
        if s.empty:
            return None
        name = s.name
        if not self.creative:
            s.name, s.count = None, 0
        return name

    def clear(self):
        for s in self.slots:
            s.name, s.count = None, 0
        self.cursor = Slot()

    # ---------- 创造模式物品列表 ----------
    def fill_creative(self):
        for i, name in enumerate(B.CREATIVE_ITEMS[:SLOTS]):
            self.slots[i] = Slot(name, 64)
        self.selected = 0

    def fill_survival_start(self, items):
        """生存模式开局给一点工具/方块。"""
        for name, count in items:
            self.add(name, count)

    # ---------- 与 UI 交互（拖拽） ----------
    def click_slot(self, index, right_click=False):
        """把鼠标手上的东西和格子里的交换/合并。"""
        s = self.slots[index]
        cur = self.cursor
        if cur.empty and s.empty:
            return
        if cur.empty:
            if right_click:
                take = (s.count + 1) // 2
                cur.name, cur.count = s.name, take
                s.count -= take
                if s.count <= 0:
                    s.name, s.count = None, 0
            else:
                cur.name, cur.count = s.name, s.count
                s.name, s.count = None, 0
            return
        if s.empty:
            if right_click:
                put = 1 if self.creative else min(1, cur.count)
                s.name, s.count = cur.name, put
                if not self.creative:
                    cur.count -= put
            else:
                s.name, s.count = cur.name, cur.count
                cur.name, cur.count = None, 0
            if cur.count <= 0:
                cur.name, cur.count = None, 0
            return
        if s.name == cur.name and s.count < 64:
            put = min(64 - s.count, 1 if right_click else cur.count)
            s.count += put
            if not self.creative:
                cur.count -= put
            if cur.count <= 0:
                cur.name, cur.count = None, 0
            return
        # 不同类型：交换
        s.name, cur.name = cur.name, s.name
        s.count, cur.count = cur.count, s.count

    def to_dict(self):
        return {
            "selected": self.selected,
            "slots": [[s.name, s.count] if not s.empty else None for s in self.slots],
        }

    def from_dict(self, d):
        if not d:
            return
        self.selected = int(d.get("selected", 0))
        for i, item in enumerate(d.get("slots", [])[:SLOTS]):
            if item:
                self.slots[i] = Slot(item[0], int(item[1]))
