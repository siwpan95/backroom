# -*- coding: utf-8 -*-
"""**装配层**：把内核（逻辑）、世界（渲染）、音床（声音）接成一个能跑的程序。

直接继承 3dworld 的 ``world3d.engine.app.EngineApp``——它已经包好了
窗口 / DPI / 主循环 / HUD / 性能面板 / 截图调度 / ``--smoke --shot --bench`` CLI，
本文件只写**后室自己的**那部分：输入语义、每帧推进、状态行。

操作
----
WASD 走　拖拽转视角　SHIFT 疾走　A 自动驾驶开关　T 换层（调试）
R 换一张新地图　SPACE 暂停　F1 HUD　F2 性能面板　ESC 退出
"""
from __future__ import annotations

import math
import os

import pyglet
from world3d.engine.app import EngineApp

from .audio import ensure_bed, load
from .kernel import SPRINT, TURN, BackroomKernel
from .world import BackroomWorld

TITLE = 'backroom · 无尽阈室 — 伪无限后室漫游（3dworld 引擎）'
HELP = ('WASD 走   拖拽 转视角   SHIFT 疾走   A 自动驾驶   T 下潜一层   '
        'R 换地图   SPACE 暂停   F1 HUD   F2 性能   ESC 退出')
SHOTS = ((8.0, 'docs/backroom_01.png'),
         (26.0, 'docs/backroom_02.png'),
         (48.0, 'docs/backroom_03.png'))
DURATION = None


class BackroomApp(EngineApp):
    TITLE = TITLE
    HELP = HELP
    SHOTS = SHOTS
    DURATION = DURATION
    SHOW_HUD = True
    FOV = 72.0
    Z_NEAR, Z_FAR = 0.08, 260.0
    CLEAR_COLOR = (0.02, 0.02, 0.018, 1.0)

    def setup(self):
        seed = self._seed()
        self.k = BackroomKernel(seed=seed)
        self.world = BackroomWorld(self.k, self.window.width, self.window.height)
        self.keys = set()
        # `--shot` 是无人值守抓帧：不动就永远停在出生点，所以也给 auto
        self.k.auto = ('auto' in self.args.flags
                       or bool(getattr(self.args, 'shot', False)))
        self._bed = None
        try:
            self._bed = load(ensure_bed(level=0))
            self._bed.volume = 0.42
            self._bed.play()
        except Exception as e:                       # noqa: BLE001
            print(f'[audio] unavailable: {e}')

    def _seed(self):
        for f in self.args.flags:
            if f.startswith('seed') and f[4:].isdigit():
                return int(f[4:])
        return 20261019

    # ------------------------------------------------------------ 输入
    def on_key(self, symbol, modifiers):
        key = pyglet.window.key
        self.keys.add(symbol)
        if symbol == key.A:
            self.k.auto = not self.k.auto
        elif symbol == key.T:
            # 调试用：手动触发一次下潜（看换层染色是否正常）
            self.k.bus.emit('anomaly_found')
            self.k.bus.emit('noclip')
            self.k.bus.emit('descend')
            self.k.bus.emit('level_change')
            self.k.bus.emit('lights_flicker')
            self.world.retint_for_level()
        elif symbol == key.R:
            self.k = BackroomKernel(seed=(self.k.seed * 1103515245 + 12345) % (2 ** 31))
            self.world.k = self.k
            self.world.refresh(force=True)

    def on_key_release(self, symbol, modifiers):
        self.keys.discard(symbol)

    def on_mouse_drag(self, x, y, dx, dy, buttons, modifiers):
        self.k.turn(-dx * 0.0042)

    # ------------------------------------------------------------ 每帧
    def update(self, dt):
        if not self.k.auto:
            key = pyglet.window.key
            k = self.keys
            fwd = (1.0 if key.W in k else 0.0) - (1.0 if key.S in k else 0.0)
            strafe = (1.0 if key.D in k else 0.0) - (1.0 if key.A in k else 0.0)
            sprint = bool(modifiers_shift(k))
            if key.LEFT in k:
                self.k.turn(TURN * dt)
            if key.RIGHT in k:
                self.k.turn(-TURN * dt)
            self.k.move(fwd, strafe, dt, sprint=sprint)
        self.k.step(dt)
        # 换层后整场重新染色（材质是程序化的，重染零成本）
        if self.k.flicker > 1.55:
            self.world.retint_for_level()
        self.world.update(dt)

    def render(self):
        self.world.render(self.window)

    def on_resize_hook(self, width, height):
        self.world.resize(width, height)

    # ------------------------------------------------------------ HUD
    def status_text(self):
        s = self.world.stats
        return (f'{self.k.status()}   '
                f'draw {s.get("draw_calls", 0)}   '
                f'块 {s.get("chunks", 0)}   '
                f'fps {self.fps:4.1f}')

    def extra_perf_lines(self):
        s = self.world.stats
        return (f'backroom: chunks={s.get("chunks", 0)} '
                f'visible={s.get("visible", 0)} culled={s.get("culled", 0)} '
                f'tris={s.get("triangles", 0)}',)


def modifiers_shift(keyset):
    key = pyglet.window.key
    return (key.LSHIFT in keyset) or (key.RSHIFT in keyset)


def main(argv=None):
    from world3d.engine.app import run
    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'docs'), exist_ok=True)
    return run(BackroomApp, argv)


if __name__ == '__main__':
    raise SystemExit(main())
