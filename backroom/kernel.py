# -*- coding: utf-8 -*-
"""**无尽阈室 / Backroom** —— 伪无限后室漫游内核（纯数学 · 零 GL · headless 可跑）。

重构定位（相对原 ``backrooms_raycaster.pyw``）
----------------------------------------------
原项目把地图 / pygame 渲染 / 实体 / 音频揉在一个 1349 行的类里。这里按
**3dworld 的分层范式**重写：本模块 = **地图 + 漫游 + 事件编排**，零 GL、零窗口，
表现层自由消费（``backroom/world.py``）。

使用的 3dworld 能力
-------------------
- ``world3d.engine.fsm.Machine`` —— 漫游状态机（时间窗 + 事件转移）
- ``world3d.engine.orchestration.Bus`` —— 声明式事件级联（踏入异常 → 下潜 → 换层 → 灯闪）
- ``world3d.engine.physics.resolve_axis`` —— 沿墙滑动碰撞（斜贴墙不卡死）
- ``world3d.engine.greedy_mesh`` 的格约定 —— 表现层可直接用 ``layer_mesh`` 合批
- ``backroom.mapgen`` —— 伪无限区块地图（本仓核心资产，零第三方依赖）

坐标约定（必须与 ``engine.greedy_mesh.layer_mesh`` 一致）
------------------------------------------------------
格 ``(i, j)``：``i`` = 行 ↔ **z**，``j`` = 列 ↔ **x**；
占据 ``x ∈ [j·CELL, (j+1)·CELL]``、``z ∈ [i·CELL, (i+1)·CELL]``。
玩家 ``yaw = 0`` 面向 **-z**（与 3dworld 相机约定一致）。
"""
from __future__ import annotations

import math
import random
from collections import deque

from world3d.engine.fsm import Machine
from world3d.engine.frustum import AABB
from world3d.engine.orchestration import Bus
from world3d.engine.physics import resolve_axis

from .mapgen import (CHUNK, TILE_ANOMALY, TILE_FLOOR, TILE_PILLAR, TILE_WALL,
                     chunk_seed, ensure_connected)

# ==================================================================== 常量
CELL = 3.0                  # 格距（米）
WALL_H = 2.9                # 墙高（后室的压抑低天花）
EYE = 1.62                  # 眼高
PLAYER_R = 0.34             # 碰撞半径
WALK = 2.55                 # 步行速度（m/s）
SPRINT = 1.55               # SHIFT 倍率
TURN = 2.4                  # 键盘转向（rad/s）
DEFAULT_SEED = 20261019

DESCEND_CHUNKS = 3          # 距原点多少个 chunk 提升一层
DESCEND_TIME = 2.0          # 下潜"坠落"持续时长（秒）
MAX_LEVEL = 4
NOCLIP_COOLDOWN = 6.0       # 两次 noclip 之间的冷却（秒）
ANOMALY_SCAN = 14           # auto-pilot 扫描异常点的格半径

#: 后室层级表：越深越"不对劲"。表现层与 HUD 直接消费。
#: (名称, 墙色, 地毯色, 天花色, 雾色, 灯色, 雾距, 灯密度, 湿度)
LEVELS = (
    ('Level 0 · 大厅', (0.42, 0.37, 0.16), (0.30, 0.27, 0.14), (0.52, 0.50, 0.42),
     (0.020, 0.020, 0.018), (1.00, 0.96, 0.82), 22.0, 1.00, 0.15),
    ('Level 1 · 仓储', (0.34, 0.30, 0.24), (0.22, 0.21, 0.18), (0.40, 0.39, 0.36),
     (0.030, 0.028, 0.024), (0.96, 0.92, 0.78), 18.0, 0.72, 0.35),
    ('Level 2 · 管道', (0.24, 0.22, 0.20), (0.15, 0.15, 0.14), (0.28, 0.28, 0.27),
     (0.040, 0.036, 0.032), (0.86, 0.84, 0.72), 14.0, 0.48, 0.55),
    ('Level 3 · 电室', (0.20, 0.19, 0.22), (0.12, 0.12, 0.14), (0.24, 0.24, 0.27),
     (0.050, 0.042, 0.046), (0.78, 0.80, 0.86), 11.0, 0.30, 0.70),
    ('Level 4 · 深处', (0.16, 0.14, 0.14), (0.09, 0.09, 0.09), (0.18, 0.17, 0.17),
     (0.062, 0.048, 0.048), (0.68, 0.64, 0.56), 8.5, 0.18, 0.85),
)
LEVEL_NAMES = tuple(lv[0] for lv in LEVELS)


class BackroomKernel:
    """伪无限后室漫游内核：地图 + 玩家 + 层级 + 事件编排 + auto-pilot。"""

    def __init__(self, seed: int = DEFAULT_SEED):
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.map = _ChunkMap(self.seed)

        sx, sz = self.map.find_spawn(0, 0)
        self.x, self.z = sx, sz
        self.yaw = self.rng.uniform(0.0, math.tau)

        self.t = 0.0
        self.dist = 0.0
        self.level = 0
        self.descents = 0
        self.chunks_seen: set[tuple[int, int]] = set()
        self.noclip_cd = 0.0
        self.flicker = 0.0          # 灯闪剩余（表现层消费）
        self.flash = 0.0            # 下潜白闪剩余
        self.last_event = ''
        self._chunk = None

        self.fsm = self._build_fsm()
        self.bus = self._build_bus()
        self.fsm.fire('boot', 0.0)          # 进入 settling
        self._descend_t = -1.0              # 进入 descending 的时刻（-1 = 未在下潜）
        self.auto = False
        self._pilot = _AutoPilot(self)
        self._sync_chunk()

    # ------------------------------------------------------------ 状态机
    def _build_fsm(self) -> Machine:
        # 时间窗（time=）留给"时间轴查询型"状态机（at(t) 回看）；
        # 这里是**事件驱动**型，状态切换全靠 fire()，故一律不声明时间窗。
        m = Machine('backroom')
        m.state('settling')
        m.state('wandering')
        m.state('anomaly')
        m.state('descending')
        m.transition('entered', 'settling', 'wandering')
        m.transition('anomaly_found', 'wandering', 'anomaly')
        m.transition('noclip', 'anomaly', 'descending')
        m.transition('landed', 'descending', 'wandering')
        m.transition('back', 'anomaly', 'wandering')
        # Machine._current 初值是 None，必须有一个从任意态进入 settling 的入口，
        # 否则 settled→wandering 永远匹配不上（current 一直是 None）。
        m.transition('boot', '*', 'settling')
        return m

    def _build_bus(self) -> Bus:
        b = Bus('backroom')
        b.on('enter_chunk', self._on_enter_chunk)
        b.on('anomaly_found', self._on_anomaly)
        b.on('noclip', self._on_noclip)
        b.on('descend', self._on_descend)
        b.on('level_change', self._on_level_change)
        b.on('lights_flicker', self._on_flicker)
        b.on('landed', self._on_landed)
        b.bind('anomaly_found', 'noclip')
        b.bind('noclip', 'descend')
        b.bind('descend', 'level_change')
        b.bind('level_change', 'lights_flicker')
        b.bind('lights_flicker', 'landed')
        return b

    def _on_enter_chunk(self, ev, p):
        c = p.get('chunk')
        if c is not None:
            self.chunks_seen.add(c)

    def _on_anomaly(self, ev, p):
        self.last_event = '地面在脚下软了一下。'

    def _on_noclip(self, ev, p):
        self.noclip_cd = NOCLIP_COOLDOWN
        self.last_event = '……你穿过去了。'
        self._teleport()

    def _teleport(self):
        """noclip 的位移：坠到这一层的另一处（10~24 格外，优先未探索区块）。

        只改层级而不位移的话，玩家会站在同一格上被反复 noclip
        （实测 150s 内触发 25 次、区块永远停在出生块）——既不合理，
        也让"伪无限地图"这条主线永远走不到。
        """
        gx, gy = self.nearest_open(self.x, self.z)
        rng = random.Random((self.seed * 104729 + self.descents * 7919) & 0x7FFFFFFF)
        seen = self.chunks_seen
        cands = []
        for _ in range(80):
            d = rng.randint(10, 24)
            ang = rng.uniform(0, math.tau)
            tx, ty = gx + int(math.cos(ang) * d), gy + int(math.sin(ang) * d)
            if self.tile_at((tx + 0.5) * CELL, (ty + 0.5) * CELL) in (TILE_WALL, TILE_PILLAR):
                continue
            cands.append(((tx // CHUNK, ty // CHUNK) not in seen, (tx, ty)))
        if not cands:
            return
        # 优先落在没去过的区块
        fresh = [c for want, c in cands if want]
        tx, ty = (fresh or [c for _, c in cands])[0]
        self.x, self.z = (tx + 0.5) * CELL, (ty + 0.5) * CELL
        self._pilot.route, self._pilot.idx, self._pilot.goal = [], 0, None

    def _on_descend(self, ev, p):
        self.descents += 1
        self.flash = 0.55

    def _on_level_change(self, ev, p):
        self.level = min(self.level + 1, MAX_LEVEL)

    def _on_flicker(self, ev, p):
        self.flicker = 1.6

    def _on_landed(self, ev, p):
        self.last_event = f'抵达 {LEVEL_NAMES[self.level]}。'

    # ------------------------------------------------------------ 地图查询
    def tile_at(self, wx: float, wz: float) -> int:
        return self.map.tile_at(wx, wz)

    def is_solid(self, wx: float, wz: float) -> bool:
        return self.tile_at(wx, wz) in (TILE_WALL, TILE_PILLAR)

    def chunk(self) -> tuple[int, int]:
        return self._chunk or (0, 0)

    def visible_chunks(self, radius: int = 1):
        """玩家周边区块（渲染只建这些）——伪无限的关键：只建视野内的。"""
        cx, cy = self.chunk()
        return [(cx + i, cy + j)
                for i in range(-radius, radius + 1)
                for j in range(-radius, radius + 1)]

    # ------------------------------------------------------------ 移动
    def move(self, fwd: float, strafe: float, dt: float, sprint: bool = False):
        """位移 + 沿墙滑动。

        真用 ``world3d.engine.physics.resolve_axis`` 的**分轴解算**：
        把玩家包成 AABB，只取周边墙格做碰撞体，X 轴先解、Z 轴后解——
        撞墙时该轴被推回、另一轴照走，于是天然产生"沿墙滑动"，不会卡死在墙角。
        """
        sp = WALK * (SPRINT if sprint else 1.0)
        sy, cy = math.sin(self.yaw), math.cos(self.yaw)
        dx = (-sy * fwd + cy * strafe) * sp * dt
        dz = (-cy * fwd - sy * strafe) * sp * dt
        if dx == 0.0 and dz == 0.0:
            return

        ox, oz = self.x, self.z
        walls = self.near_walls()
        for axis, vel in ((0, dx), (2, dz)):
            box = AABB.from_center_half((self.x, EYE, self.z),
                                        (PLAYER_R, EYE * 0.9, PLAYER_R))
            box.min = (box.min[0] + (vel if axis == 0 else 0.0), box.min[1],
                       box.min[2] + (vel if axis == 2 else 0.0))
            box.max = (box.max[0] + (vel if axis == 0 else 0.0), box.max[1],
                       box.max[2] + (vel if axis == 2 else 0.0))
            hit, _normal = resolve_axis(box, walls, axis, vel)
            # 解算后把 box 推回的位置写回玩家中心
            if hit:
                if axis == 0:
                    self.x = (box.min[0] + box.max[0]) * 0.5
                else:
                    self.z = (box.min[2] + box.max[2]) * 0.5
            else:
                if axis == 0:
                    self.x += vel
                else:
                    self.z += vel

        self.dist += math.hypot(self.x - ox, self.z - oz)

    def near_walls(self, radius: int = 3) -> list:
        """玩家周边 radius 格内的墙格 AABB（碰撞体）。

        伪无限地图不能全量建碰撞体——只取身边这几格，常数可控。
        """
        gx, gy = int(math.floor(self.x / CELL)), int(math.floor(self.z / CELL))
        out = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                tx, ty = gx + dx, gy + dy
                if self.map.tile_at((tx + 0.5) * CELL, (ty + 0.5) * CELL) not in (
                        TILE_WALL, TILE_PILLAR):
                    continue
                x0, z0 = tx * CELL, ty * CELL
                out.append(AABB((x0, 0.0, z0), (x0 + CELL, WALL_H, z0 + CELL)))
        return out

    def turn(self, d: float):
        self.yaw = (self.yaw + d) % math.tau

    # ------------------------------------------------------------ 每帧推进
    def step(self, dt: float):
        dt = min(dt, 0.05)                      # 卡帧保护
        self.t += dt
        self.flicker = max(0.0, self.flicker - dt)
        self.flash = max(0.0, self.flash - dt)
        self.noclip_cd = max(0.0, self.noclip_cd - dt)

        if self.auto:
            f, s, turn = self._pilot.step(dt)
            self.turn(turn)
            self.move(f, s, dt)

        self._sync_chunk()

        # 踏入异常区 → 走「发现 → noclip → 下潜 → 换层 → 灯闪 → 落地」级联
        if (self.fsm.current == 'wandering' and self.noclip_cd <= 0.0
                and self.tile_at(self.x, self.z) == TILE_ANOMALY):
            self.fsm.fire('anomaly_found', self.t)
            self.bus.emit('anomaly_found',
                          tile=(int(self.x / CELL), int(self.z / CELL)))
            if self.fsm.current == 'anomaly':
                self.fsm.fire('noclip', self.t)

        if self.fsm.current == 'settling' and self.t > 2.5:
            self.fsm.fire('entered', self.t)
        elif self.fsm.current == 'descending':
            # 下潜是一段"坠落"，持续 DESCEND_TIME 秒后再落地（不是一帧闪过）
            if self._descend_t < 0.0:
                self._descend_t = self.t
            elif self.t - self._descend_t >= DESCEND_TIME:
                self._descend_t = -1.0
                self.fsm.fire('landed', self.t)

    def _sync_chunk(self):
        c = (int(math.floor(self.x / CELL)) // CHUNK,
             int(math.floor(self.z / CELL)) // CHUNK)
        if c != self._chunk:
            self._chunk = c
            self.bus.emit('enter_chunk', chunk=c)
            # 深度按切比雪夫距离分层
            target = min(max(abs(c[0]), abs(c[1])) // DESCEND_CHUNKS, MAX_LEVEL)
            if target > self.level:
                self.level = target

    # ------------------------------------------------------------ 快照
    def level_info(self) -> dict:
        lv = LEVELS[min(self.level, MAX_LEVEL)]
        return dict(name=lv[0], wall=lv[1], carpet=lv[2], ceil=lv[3],
                    fog=lv[4], lamp=lv[5], fog_far=lv[6],
                    lamp_density=lv[7], damp=lv[8])

    def status(self) -> str:
        info = self.level_info()
        return (f'{info["name"]}   chunk {self.chunk()}   '
                f'已探索 {len(self.chunks_seen)} 区块   下潜 {self.descents}   '
                f'{self.dist:6.1f}m   t={self.t:5.1f}s   [{self.fsm.current}]'
                f'{"  [AUTO]" if self.auto else ""}')

    # ------------------------------------------------------------ 寻路
    def path(self, a, b):
        """格坐标 BFS 最短路（含端点）；不可达返回空表。"""
        return self.map.path(a, b)

    def nearest_open(self, wx, wz, radius=6):
        return self.map.nearest_open(wx, wz, radius)


class _ChunkMap:
    """伪无限区块地图（按需生成 + 缓存）。

    算法直接继承原 backroom（递归回溯迷宫 → 打通开放空间 → 孤岛连通兜底 →
    房间 → 异常区），只把"区块化 / 世界坐标查询 / 寻路"这层做扎实。
    """

    def __init__(self, seed: int):
        self.seed = int(seed)
        self.cache: dict[tuple[int, int], list[list[int]]] = {}

    # ---- 生成
    def grid(self, cx: int, cy: int) -> list[list[int]]:
        key = (int(cx), int(cy))
        g = self.cache.get(key)
        if g is not None:
            return g
        rng = random.Random(chunk_seed(key[0], key[1], self.seed))
        g = self._carve(CHUNK, rng)
        self._rooms(g, rng)
        self._anomalies(g, rng)
        ensure_connected(g)          # 所有可走格互通（异常染色会切断通路）
        self.cache[key] = g
        return g

    @staticmethod
    def _carve(size, rng):
        grid = [[TILE_WALL] * size for _ in range(size)]

        def dig(x, y):
            dirs = [(0, -2), (2, 0), (0, 2), (-2, 0)]
            rng.shuffle(dirs)
            for dx, dy in dirs:
                nx, ny = x + dx * 2, y + dy * 2
                if 1 <= nx < size - 1 and 1 <= ny < size - 1 and grid[ny][nx] == TILE_WALL:
                    grid[y + dy][x + dx] = TILE_FLOOR
                    grid[ny][nx] = TILE_FLOOR
                    dig(nx, ny)

        grid[1][1] = TILE_FLOOR
        dig(1, 1)
        for _ in range(size * 3):                     # 打通若干墙 → 开阔感
            x, y = rng.randint(1, size - 2), rng.randint(1, size - 2)
            if grid[y][x] == TILE_WALL:
                grid[y][x] = TILE_FLOOR

        floors = [(x, y) for y in range(size) for x in range(size)
                  if grid[y][x] == TILE_FLOOR]
        if floors:
            main = _ChunkMap._bfs(grid, *floors[0])
            for ix, iy in [(x, y) for x, y in floors if (x, y) not in main]:
                nx_, ny_ = min(main, key=lambda c: abs(c[0] - ix) + abs(c[1] - iy))
                x, y = nx_, ny_
                while x != ix:
                    if 0 < x < size - 1:
                        grid[y][x] = TILE_FLOOR
                    x += 1 if x < ix else -1
                while y != iy:
                    if 0 < y < size - 1:
                        grid[y][x] = TILE_FLOOR
                    y += 1 if y < iy else -1
                grid[iy][ix] = TILE_FLOOR
        return grid

    @staticmethod
    def _bfs(grid, sx, sy):
        n = len(grid)
        seen, q = set(), deque([(sx, sy)])
        while q:
            x, y = q.popleft()
            if (x, y) in seen or not (0 <= x < n and 0 <= y < n):
                continue
            if grid[y][x] != TILE_FLOOR:
                continue
            seen.add((x, y))
            q.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
        return seen

    def _rooms(self, g, rng):
        h, w = len(g), len(g[0])
        for _ in range(rng.randint(2, 3)):
            rw, rh = rng.randint(4, 5), rng.randint(4, 5)
            rx = rng.randint(2, max(2, w - rw - 2))
            ry = rng.randint(2, max(2, h - rh - 2))
            for y in range(ry, ry + rh):
                for x in range(rx, rx + rw):
                    if 0 <= y < h and 0 <= x < w:
                        g[y][x] = TILE_FLOOR
            if rng.random() > 0.6:
                g[ry + rh // 2][rx + rw // 2] = TILE_PILLAR

    def _anomalies(self, g, rng):
        h, w = len(g), len(g[0])
        for _ in range(rng.randint(2, 5)):
            x, y = rng.randint(1, w - 2), rng.randint(1, h - 2)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and rng.random() > 0.5:
                        g[ny][nx] = TILE_ANOMALY

    # ---- 查询
    def tile_at(self, wx: float, wz: float) -> int:
        gx, gy = int(math.floor(wx / CELL)), int(math.floor(wz / CELL))
        cx, cy = gx // CHUNK, gy // CHUNK
        g = self.grid(cx, cy)
        return g[gy % CHUNK][gx % CHUNK]

    def find_spawn(self, cx: int, cy: int) -> tuple[float, float]:
        """区块内找一个 3×3 全空的出生点（返回世界米坐标）。"""
        rng = random.Random(chunk_seed(cx, cy, self.seed) ^ 0x5EED)
        g = self.grid(cx, cy)
        opens = [(x, y) for y in range(CHUNK) for x in range(CHUNK)
                 if g[y][x] == TILE_FLOOR]
        if not opens:
            return (cx * CHUNK + 1.5) * CELL, (cy * CHUNK + 1.5) * CELL
        rng.shuffle(opens)
        for x, y in opens[:400]:
            if all(0 <= y + dy < CHUNK and 0 <= x + dx < CHUNK
                   and g[y + dy][x + dx] == TILE_FLOOR
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                return ((cx * CHUNK + x + 0.5) * CELL,
                        (cy * CHUNK + y + 0.5) * CELL)
        x, y = opens[0]
        return ((cx * CHUNK + x + 0.5) * CELL, (cy * CHUNK + y + 0.5) * CELL)

    def nearest_open(self, wx, wz, radius=6):
        gx, gy = int(math.floor(wx / CELL)), int(math.floor(wz / CELL))
        for r in range(radius + 1):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    t = self.tile_at((gx + dx + 0.5) * CELL, (gy + dy + 0.5) * CELL)
                    if t in (TILE_FLOOR, TILE_ANOMALY):
                        return gx + dx, gy + dy
        return gx, gy

    def path(self, a, b):
        """格坐标 BFS 最短路（含端点）；不可达返回空表。"""
        if a == b:
            return [a]
        prev, q, seen = {a: None}, deque([a]), {a}
        while q:
            cur = q.popleft()
            if cur == b:
                break
            x, y = cur
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in seen:
                    continue
                if self.tile_at((nx + 0.5) * CELL, (ny + 0.5) * CELL) in (TILE_WALL, TILE_PILLAR):
                    continue
                seen.add((nx, ny))
                prev[(nx, ny)] = cur
                q.append((nx, ny))
        if b not in prev:
            return []
        out, cur = [], b
        while cur is not None:
            out.append(cur)
            cur = prev[cur]
        return out[::-1]


class _AutoPilot:
    """自动驾驶：挑远处目标 → BFS 寻路 → 沿路走。

    ``--shot``（无人值守抓帧）与 headless 验收共用**同一套**逻辑，
    避免"演示能跑、验收跑不了"的双实现漂移。
    """

    def __init__(self, k: BackroomKernel):
        self.k = k
        self.rng = random.Random(k.seed ^ 0xA5A5)
        self.goal = None
        self.route: list = []
        self.idx = 0

    def _seek_anomaly(self):
        """优先找附近的可达异常格（noclip 点）——后室的核心动作就是"找不对劲的地方"。

        纯随机游走会一直在同一区块内打转：既走不出区块（伪无限等于没验证），
        也踩不到异常格（下潜链路永远不触发）。所以目标选择必须是**有偏好**的。
        """
        k = self.k
        gx, gy = k.nearest_open(k.x, k.z)
        best, best_d = None, 1e9
        for dy in range(-ANOMALY_SCAN, ANOMALY_SCAN + 1):
            for dx in range(-ANOMALY_SCAN, ANOMALY_SCAN + 1):
                tx, ty = gx + dx, gy + dy
                if k.tile_at((tx + 0.5) * CELL, (ty + 0.5) * CELL) != TILE_ANOMALY:
                    continue
                d = abs(dx) + abs(dy)
                if d < best_d and len(k.map.path((gx, gy), (tx, ty))) >= 2:
                    best, best_d = (tx, ty), d
        if best is not None:
            self.goal, self.route, self.idx = best, k.map.path((gx, gy), best), 1
            return True
        return False

    def _pick_goal(self):
        """挑目标：先看有没有异常点，否则朝**未探索区块**方向远行。

        方向偏好未探索区块，才能让"伪无限地图"真正被走到（否则永远卡在出生块）。
        """
        # 探索为主、下潜为辅：多数时候往没去过的区块远行，偶尔才去找异常点。
        # 反过来（异常优先）会让玩家钉在出生块反复 noclip，伪无限地图走不出去。
        k = self.k
        if len(k.chunks_seen) >= 2 and self.rng.random() < 0.35:
            if self._seek_anomaly():
                return
        k = self.k
        gx, gy = k.nearest_open(k.x, k.z)
        rng = random.Random((k.seed * 7919 + int(k.t * 13)) & 0xFFFF)
        seen = k.chunks_seen
        for _ in range(60):
            d = rng.randint(10, 20)
            ang = rng.uniform(0, math.tau)
            tx = gx + int(math.cos(ang) * d)
            ty = gy + int(math.sin(ang) * d)
            if k.tile_at((tx + 0.5) * CELL, (ty + 0.5) * CELL) in (TILE_WALL, TILE_PILLAR):
                continue
            r = k.map.path((gx, gy), (tx, ty))
            if len(r) < 4:
                continue
            # 目标所在区块越"新"越好
            tgt_chunk = (tx // CHUNK, ty // CHUNK)
            if tgt_chunk not in seen:
                self.goal, self.route, self.idx = (tx, ty), r, 1
                return
            if self.goal is None:
                self.goal, self.route, self.idx = (tx, ty), r, 1
        if not self.route:
            self.route, self.idx, self.goal = [], 0, None

    def step(self, dt: float):
        """返回 (forward, strafe, turn_delta)。"""
        k = self.k
        if not self.route or self.idx >= len(self.route):
            self._pick_goal()
            if not self.route:
                return 1.0, 0.0, 0.35
        tx, ty = self.route[min(self.idx, len(self.route) - 1)]
        wx, wz = (tx + 0.5) * CELL, (ty + 0.5) * CELL
        dx, dz = wx - k.x, wz - k.z
        if math.hypot(dx, dz) < 0.45:
            self.idx += 1
            if self.idx >= len(self.route):
                self.route = []
            return 1.0, 0.0, 0.0
        want = math.atan2(-dx, -dz)                  # yaw=0 面向 -z
        diff = (want - k.yaw + math.pi) % math.tau - math.pi
        turn = max(-TURN * dt, min(TURN * dt, diff * 3.0))
        return (1.0 if abs(diff) < 1.1 else 0.25), 0.0, turn
