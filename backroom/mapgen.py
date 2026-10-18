# -*- coding: utf-8 -*-
"""backroom · 地图层（**仅地图**，零第三方依赖）

从 ``backrooms_raycaster.pyw``（1349 行 pygame 光线投射演示）中**剥离出来的纯地图内核**：
去掉渲染器、音频引擎、玩家、实体（entity）、道具（item）与主循环，
只保留「后室伪无限地图」的生成与查询。

## 为什么单独拆出来

原文件把地图 / 渲染 / 玩法 / 音频揉在一个类里，地图无法被别的引擎复用。
本模块只依赖标准库（``random`` / ``math``），Python 3.8+ 可直接 import，
因此能被任何渲染后端消费（D:\\projects\\3dworld 的 pyglet 三维管线即其一）。

## 保留的能力（原样搬移，行为等价）

- **伪无限地图**：世界按 ``CHUNK``(24)×24 切块，按需生成 + LRU 式缓存；
- **递归回溯迷宫**：奇数坐标雕刻，保证区块内连通；
- **额外连通**：随机打通 ``size*3`` 面墙制造开放空间，并对孤立地板补 L 形通路
  （原 ``_generate_maze_recursive`` 的 BFS 连通性兜底）；
- **大型房间**：``_add_rooms`` 挖矩形房间，概率在中心落 ``TILE_PILLAR``(2)；
- **异常区域**：``_add_anomalies`` 在 3×3 邻域概率落 ``TILE_ANOMALY``(3)；
- **世界坐标查询**：``get_tile(world_x, world_y)`` 跨区块透明取格。

## 相对原实现的两处修正（有意为之，非行为漂移）

1. ``_seed_from_chunk`` 原用内置 ``hash((cx, cy, seed))``——元组哈希在解释器
   实现层面不保证跨版本/跨进程稳定。改为显式整数混合
   （``cx*73856093 ^ cy*19349663 ^ seed*83492791``），保证**同一 seed 永远生成同一张图**。
2. 原 ``generate_level`` 调用了**未定义**的 ``self._divide``（实测 ``AttributeError``），
   且同文件里被**重复定义两次**（后者覆盖前者）。本模块补齐 BSP 版 ``_divide``
   并只保留一份，``generate_level`` 才真正可用。

## 用法

    from backroom_mapgen import BackroomsGenerator
    gen = BackroomsGenerator(seed=42)
    gen.get_tile(10.5, 3.2)      # -> 0/1/2/3
    grid = gen.generate_chunk(0, 0)   # 24x24 二维列表

许可：MIT-0（随本仓）。
"""
from __future__ import annotations

import math
import random

# ------------------------------------------------------------------ 格子语义
TILE_FLOOR = 0    # 可行走地板
TILE_WALL = 1     # 墙（默认填充）
TILE_PILLAR = 2   # 房间中心标记（后室常见的孤立柱/物件位）
TILE_ANOMALY = 3  # 异常区域（noclip 点 / 装修异常）

#: 世界边界外一律视为墙（玩家走不出去）
OUT_OF_RANGE = TILE_WALL

CHUNK = 24            # 每个区块的边长（格）
DEFAULT_ROOMS_MIN = 2      # 每区块最少房间数
DEFAULT_ROOMS_MAX = 3      # 每区块最多房间数
DEFAULT_ROOM_MAX_SIZE = 5  # 房间最大边长


def ensure_connected(grid):
    """保证区块内**所有可走格互通**（可走 = FLOOR / ANOMALY）。

    为什么需要这道兜底：``_add_anomalies`` 会把地板染成 ``TILE_ANOMALY``，
    在"仅 FLOOR"视角下等于把走廊切断；而底边/角落又常生成被墙包死的孤立格
    （实测 seed=7 的 chunk 在 y=22 有两个永远走不到的 A）。
    结果是"地图上画着能走、实际到不了"——玩家视角就是死路。

    做法：取最大连通域，把其余各簇用 L 形通路接回主域（而不是简单填成墙，
    填墙会白白丢掉房间与异常区的面积）。
    """
    h, w = len(grid), len(grid[0]) if grid else 0
    if h == 0 or w == 0:
        return grid

    walkable = {(x, y) for y in range(h) for x in range(w)
                if grid[y][x] in (TILE_FLOOR, TILE_ANOMALY)}
    if not walkable:
        return grid

    # ---- 求所有连通分量
    seen, comps = set(), []
    for cell in walkable:
        if cell in seen:
            continue
        comp, stack = set(), [cell]
        seen.add(cell)
        while stack:
            x, y = stack.pop()
            comp.add((x, y))
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in walkable and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        comps.append(comp)

    comps.sort(key=len, reverse=True)
    main = comps[0]
    for comp in comps[1:]:
        # 找主域与本簇最近的一对，L 形挖通（保持贴边不破边界）
        best, bd = None, 1 << 30
        for ax, ay in comp:
            for bx, by in main:
                d = abs(ax - bx) + abs(ay - by)
                if d < bd:
                    bd, best = d, ((ax, ay), (bx, by))
        (ax, ay), (bx, by) = best
        x, y = bx, by
        while x != ax:
            x += 1 if x < ax else -1
            if 0 < x < w - 1:
                grid[y][x] = TILE_FLOOR
        while y != ay:
            y += 1 if y < ay else -1
            if 0 < y < h - 1:
                grid[y][x] = TILE_FLOOR
        main |= comp
    return grid


def chunk_seed(cx: int, cy: int, seed: int) -> int:
    """由区块坐标 + 主种子派生**确定性**子种子。

    替代原实现的 ``hash((cx, cy, seed))``：内置元组哈希不作跨进程稳定承诺，
    显式整数混合才能锁死「同 seed 同地图」这一可复现性前提。
    """
    h = (cx * 73856093) ^ (cy * 19349663) ^ (seed * 83492791)
    return abs(h) % 1000000


class BackroomsGenerator:
    """后室伪无限地图生成器（纯逻辑，无渲染 / 无实体 / 无音频）。"""

    def __init__(self, seed=None, chunk_size=CHUNK):
        self.seed = int(seed) if seed is not None else random.randint(0, 9999)
        self.random = random.Random(self.seed)
        self.chunk_size = int(chunk_size)

        # 区块缓存（伪无限地图的关键：走过的地方留着，没走过的不占内存）
        self.chunk_cache = {}

    # ------------------------------------------------------------ 区块生成
    def generate_chunk(self, cx, cy):
        """生成（并返回）指定区块的格子；已生成过则直接命中缓存。"""
        key = (int(cx), int(cy))
        if key in self.chunk_cache:
            return self.chunk_cache[key]

        rng = random.Random(chunk_seed(key[0], key[1], self.seed))
        size = self.chunk_size

        # 递归回溯法生成连通迷宫
        grid = self._generate_maze_recursive(size, rng)
        # 添加大型房间（增加探索空间）
        self._add_rooms(grid, DEFAULT_ROOMS_MIN, DEFAULT_ROOMS_MAX,
                        DEFAULT_ROOM_MAX_SIZE, rng)
        # 添加异常区域
        self._add_anomalies(grid, rng)
        # 兜底：保证所有可走格互通（异常染色与角落噪声会切断通路）
        ensure_connected(grid)

        self.chunk_cache[key] = grid
        return grid

    def _generate_maze_recursive(self, size, rng):
        """递归回溯法生成完全连通的迷宫（奇数坐标雕刻）。"""
        grid = [[TILE_WALL for _ in range(size)] for _ in range(size)]

        def carve(x, y):
            directions = [(0, -2), (2, 0), (0, 2), (-2, 0)]
            rng.shuffle(directions)
            for dx, dy in directions:
                nx, ny = x + dx * 2, y + dy * 2
                if 1 <= nx < size - 1 and 1 <= ny < size - 1 and grid[ny][nx] == TILE_WALL:
                    grid[y + dy][x + dx] = TILE_FLOOR
                    grid[ny][nx] = TILE_FLOOR
                    carve(nx, ny)

        grid[1][1] = TILE_FLOOR
        carve(1, 1)

        # 打通墙壁创建开放空间（后室不是规整迷宫，要"憋闷中突然开阔"）
        for _ in range(size * 3):
            x = rng.randint(1, size - 2)
            y = rng.randint(1, size - 2)
            if grid[y][x] == TILE_WALL:
                grid[y][x] = TILE_FLOOR

        # ---- 连通性兜底：把所有孤立地板接回主连通域
        all_floors = [(x, y) for y in range(size) for x in range(size)
                      if grid[y][x] == TILE_FLOOR]
        if not all_floors:
            return [[TILE_WALL for _ in range(size)] for _ in range(size)]

        connected = self._bfs_connected(grid, all_floors[0][0], all_floors[0][1])
        connected_set = set(connected)
        isolated = [(x, y) for x, y in all_floors if (x, y) not in connected_set]

        for ix, iy in isolated:
            nearest, min_dist = None, float('inf')
            for cx, cy in connected:
                dist = abs(cx - ix) + abs(cy - iy)
                if dist < min_dist:
                    min_dist, nearest = dist, (cx, cy)
            if not nearest:
                continue
            # 画 L 形路径把孤岛接回大陆
            x, y = nearest
            while x != ix:
                if 0 < x < size - 1:
                    grid[y][x] = TILE_FLOOR
                x += 1 if x < ix else -1
            while y != iy:
                if 0 < y < size - 1:
                    grid[y][x] = TILE_FLOOR
                y += 1 if y < iy else -1
            if 0 < ix < size - 1 and 0 < iy < size - 1:
                grid[iy][ix] = TILE_FLOOR

        return grid

    @staticmethod
    def _bfs_connected(grid, start_x, start_y):
        """从起点 BFS 出所有连通的地板格。"""
        size = len(grid)
        visited = set()
        queue = [(start_x, start_y)]
        while queue:
            x, y = queue.pop(0)
            if (x, y) in visited:
                continue
            if not (0 <= x < size and 0 <= y < size):
                continue
            if grid[y][x] != TILE_FLOOR:
                continue
            visited.add((x, y))
            queue.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
        return visited

    def _add_rooms(self, grid, min_rooms, max_rooms, max_size, rng):
        """挖大型房间；概率在中心落 TILE_PILLAR。"""
        height = len(grid)
        width = len(grid[0]) if height else 0
        if width < 6 or height < 6:
            return
        num_rooms = rng.randint(min_rooms, max_rooms)

        for _ in range(num_rooms):
            room_w = rng.randint(4, max_size)
            room_h = rng.randint(4, max_size)
            room_x = rng.randint(2, max(2, width - room_w - 2))
            room_y = rng.randint(2, max(2, height - room_h - 2))

            for y in range(room_y, room_y + room_h):
                for x in range(room_x, room_x + room_w):
                    if 0 <= y < height and 0 <= x < width:
                        grid[y][x] = TILE_FLOOR

            if rng.random() > 0.6:
                center_x = room_x + room_w // 2
                center_y = room_y + room_h // 2
                if 0 <= center_y < height and 0 <= center_x < width:
                    grid[center_y][center_x] = TILE_PILLAR

    def _add_anomalies(self, grid, rng):
        """在 3×3 邻域概率落 TILE_ANOMALY（后室的"装修不对劲"区域）。"""
        height = len(grid)
        width = len(grid[0]) if height else 0
        for _ in range(rng.randint(2, 5)):
            x = rng.randint(1, width - 2)
            y = rng.randint(1, height - 2)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width:
                        if rng.random() > 0.5:
                            grid[ny][nx] = TILE_ANOMALY

    # ------------------------------------------------------------ 世界查询
    def get_tile(self, world_x, world_y):
        """世界坐标（浮点格坐标）→ 格子类型；越界视为墙。"""
        size = self.chunk_size
        cx = int(world_x) // size
        cy = int(world_y) // size
        local_x = int(world_x) % size
        local_y = int(world_y) % size
        if local_x < 0:
            local_x += size
        if local_y < 0:
            local_y += size

        chunk = self.generate_chunk(cx, cy)
        if 0 <= local_y < len(chunk) and 0 <= local_x < len(chunk[0]):
            return chunk[local_y][local_x]
        return OUT_OF_RANGE

    def is_walkable(self, world_x, world_y):
        """是否可行走（异常区域视为可进入，房间中心标记视为障碍）。"""
        return self.get_tile(world_x, world_y) in (TILE_FLOOR, TILE_ANOMALY)

    def chunk_coord(self, world_x, world_y):
        """世界坐标 → 所属区块坐标。"""
        return int(world_x) // self.chunk_size, int(world_y) // self.chunk_size

    def find_spawn(self, rng=None, near=(0.0, 0.0), radius=20.0, tries=200):
        """找一个 3×3 全空的安全出生点（原 ``generate_entities`` 的逻辑，去掉实体部分）。

        返回 ``(x, y)`` 浮点坐标；找不到则退回 ``near``。
        """
        rng = rng or self.random
        for _ in range(tries):
            x = rng.uniform(near[0] + 2, near[0] + radius)
            y = rng.uniform(near[1] + 2, near[1] + radius)
            if all(self.get_tile(x + dx, y + dy) == TILE_FLOOR
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                return (x, y)
        return (near[0] + 2.0, near[1] + 2.0)

    # --------------------------------------------------- 固定尺寸关卡（BSP）
    def generate_level(self, width=32, height=32):
        """生成固定大小的后室迷宫（BSP 分割 + 房间 + 异常）。

        原实现调用未定义的 ``_divide`` 必然 AttributeError；此处补齐实现。
        """
        grid = [[TILE_WALL for _ in range(width)] for _ in range(height)]
        rng = random.Random(self.seed)
        self._divide(grid, 1, 1, width - 2, height - 2, rng)

        # 四周封边
        for y in range(height):
            grid[y][0] = TILE_WALL
            grid[y][width - 1] = TILE_WALL
        for x in range(width):
            grid[0][x] = TILE_WALL
            grid[height - 1][x] = TILE_WALL

        self._add_rooms(grid, 3, 6, 8, rng)
        self._add_anomalies(grid, rng)
        return grid

    def _divide(self, grid, x, y, w, h, rng, depth=0):
        """BSP 递归分割：把区域切成房间并开出通路。"""
        if w < 6 or h < 6 or depth > 6:
            # 太小了：整块挖成房间
            for yy in range(y, min(y + h, len(grid))):
                for xx in range(x, min(x + w, len(grid[0]))):
                    grid[yy][xx] = TILE_FLOOR
            return

        horizontal = rng.random() < (w / (w + h))
        if horizontal:
            cut = rng.randint(h // 3, 2 * h // 3)
            self._divide(grid, x, y, w, cut, rng, depth + 1)
            self._divide(grid, x, y + cut, w, h - cut, rng, depth + 1)
            # 在分割线上开一个门
            door_x = rng.randint(x + 1, x + w - 2)
            grid[min(y + cut, len(grid) - 1)][door_x] = TILE_FLOOR
        else:
            cut = rng.randint(w // 3, 2 * w // 3)
            self._divide(grid, x, y, cut, h, rng, depth + 1)
            self._divide(grid, x + cut, y, w - cut, h, rng, depth + 1)
            door_y = rng.randint(y + 1, y + h - 2)
            grid[door_y][min(x + cut, len(grid[0]) - 1)] = TILE_FLOOR

    # ------------------------------------------------------------ 调试/统计
    def stats(self, grid):
        """统计各格子类型占比（验收连通性 / 房间率时好用）。"""
        counts = {}
        for row in grid:
            for t in row:
                counts[t] = counts.get(t, 0) + 1
        total = sum(counts.values()) or 1
        return {t: (n, round(n / total * 100, 1)) for t, n in sorted(counts.items())}

    def walkable_ratio(self, grid):
        n = sum(1 for row in grid for t in row if t in (TILE_FLOOR, TILE_ANOMALY))
        total = sum(len(row) for row in grid) or 1
        return n / total


# ------------------------------------------------------------------ 自测入口
def _selfcheck():
    gen = BackroomsGenerator(seed=42)
    grid = gen.generate_chunk(0, 0)
    assert len(grid) == CHUNK and len(grid[0]) == CHUNK

    # 1) 确定性：同 seed 两次生成必须逐格相等
    again = BackroomsGenerator(seed=42).generate_chunk(0, 0)
    assert again == grid, 'seed 不可复现'

    # 2) 不同区块应产出不同地图（否则"伪无限"没意义）
    other = gen.generate_chunk(3, -1)
    assert other != grid, '区块种子退化'

    # 3) 连通性：地板格应全部从 (1,1) 可达
    reach = BackroomsGenerator._bfs_connected(grid, 1, 1)
    floors = {(x, y) for y, r in enumerate(grid) for x, t in enumerate(r)
              if t == TILE_FLOOR}
    orphan = floors - reach
    assert not orphan, f'存在孤立地板：{sorted(orphan)[:5]}'

    # 4) 世界查询跨区块不越界、不抛异常
    for wx in (-30.5, 0.0, 12.25, 99.9):
        for wy in (-12.0, 5.5, 240.0):
            assert gen.get_tile(wx, wy) in (0, 1, 2, 3)

    # 5) 固定关卡（原实现会 AttributeError 的那条路径）
    lvl = gen.generate_level(32, 32)
    assert len(lvl) == 32 and len(lvl[0]) == 32
    assert gen.walkable_ratio(lvl) > 0.2, '固定关卡可走面积过低'

    print('backroom_mapgen selfcheck: ALL PASSED')
    print('  chunk(0,0) stats:', gen.stats(grid))
    print('  level(32x32) walkable ratio: %.1f%%' % (gen.walkable_ratio(lvl) * 100))
    print('  chunk cache size:', len(gen.chunk_cache))


if __name__ == '__main__':
    _selfcheck()
