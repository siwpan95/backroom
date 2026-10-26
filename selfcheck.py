# -*- coding: utf-8 -*-
"""backroom · 无尽阈室 —— 无头自检（不开窗口、不建 GL 上下文）。

    python selfcheck.py

只验证本仓的核心资产：``backroom/mapgen.py``（README 里写明的「伪无限区块地图
纯算法层，零第三方依赖」）。渲染/内核层（``kernel.py`` / ``world.py``）依赖
``3dworld`` 引擎，本机未安装且同级仓版本与已装 pyglet 不兼容，故不 import ——
本自检因此不碰 ``backroom/__init__.py``，直接用文件路径加载 mapgen 模块。

验证三点：
  1. 同 seed 同地图（``chunk_seed`` 是显式整数混合，跨进程稳定）；
  2. 每个区块内所有可走格（地板 + 异常区）互相连通，没有走不到的孤岛；
  3. 世界坐标查询跨区块透明且与区块内坐标自洽，出生点 3x3 全地板。
输出保持 ASCII，避免 Windows 控制台代码页差异把中文打成乱码。
"""
from __future__ import annotations

import importlib.util
import random
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAPGEN = ROOT / "backroom" / "mapgen.py"


def load_mapgen():
    """按文件路径加载 mapgen（绕开 backroom/__init__.py 对 3dworld 的依赖）。"""
    spec = importlib.util.spec_from_file_location("backroom_mapgen", MAPGEN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mg = load_mapgen()
Gen = mg.BackroomsGenerator
ANOMALY, FLOOR, PILLAR, WALL = mg.TILE_ANOMALY, mg.TILE_FLOOR, mg.TILE_PILLAR, mg.TILE_WALL
CHUNK = mg.CHUNK


def _walkable_cells(grid) -> set[tuple[int, int]]:
    """可走格 = 地板 + 异常区（异常格能踏进去，正是 noclip 入口）。"""
    return {(x, y) for y, row in enumerate(grid) for x, tile in enumerate(row)
            if tile in (FLOOR, ANOMALY)}


def _flood(grid, start: tuple[int, int]) -> set[tuple[int, int]]:
    walkable = _walkable_cells(grid)
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) in walkable and (nx, ny) not in seen:
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


# --------------------------------------------------------------------- 检查项
def check_determinism() -> str:
    """同 seed 同图、区块子种子稳定且能区分区块。"""
    # 子种子必须可复现，且 (3,-7) 与 (-7,3) 不能撞
    a = mg.chunk_seed(3, -7, 42)
    assert a == mg.chunk_seed(3, -7, 42), "chunk_seed not stable"
    assert a != mg.chunk_seed(-7, 3, 42), "chunk_seed ignores axis order"
    assert a != mg.chunk_seed(3, -7, 43), "chunk_seed ignores master seed"

    one = Gen(seed=1234)
    two = Gen(seed=1234)
    for cx, cy in ((0, 0), (2, -3), (-4, 6)):
        first = one.generate_chunk(cx, cy)
        again = two.generate_chunk(cx, cy)
        assert first == again, f"same seed differs at chunk {(cx, cy)}"
        assert len(first) == CHUNK and len(first[0]) == CHUNK, "chunk shape wrong"
        # 缓存命中必须返回同一份数据，而不是重算出一个新副本
        assert one.generate_chunk(cx, cy) is first, "chunk cache not used"

    other = Gen(seed=1235).generate_chunk(0, 0)
    assert other != one.generate_chunk(0, 0), "different seeds produced identical chunk"
    return "chunk_seed stable, same seed -> same chunk (cache hit), different seed differs"


def check_connectivity() -> str:
    """每个区块内可走格必须全连通（孤岛 = 玩家会被封死）。"""
    tiles_seen = set()
    for seed in (7, 99, 20261019):
        gen = Gen(seed=seed)
        for cx, cy in ((0, 0), (2, -3), (5, 4)):
            grid = gen.generate_chunk(cx, cy)
            walkable = _walkable_cells(grid)
            assert walkable, f"seed={seed} chunk={(cx, cy)} has no walkable tile"
            reach = _flood(grid, next(iter(walkable)))
            orphans = walkable - reach
            assert not orphans, (f"seed={seed} chunk={(cx, cy)}: "
                                 f"{len(orphans)} unreachable tiles")
            ratio = gen.walkable_ratio(grid)
            assert 0.15 < ratio < 0.95, f"walkable ratio out of range: {ratio}"
            tiles_seen.update(t for row in grid for t in row)
    assert tiles_seen <= {FLOOR, WALL, PILLAR, ANOMALY}, f"unknown tile ids: {tiles_seen}"
    return "9 chunks (3 seeds x 3 offsets): walkable tiles fully connected"


def check_world_queries() -> str:
    """世界坐标 <-> 区块内坐标自洽，出生点 3x3 全地板，固定关卡可生成。"""
    gen = Gen(seed=42)
    gen.generate_chunk(0, 0)

    # 世界坐标取到的格子，必须就是该区块网格里的同一格（含负坐标区块）。
    # 用整数格坐标：模块的 get_tile 走 int() 截断，负的小数坐标会向 0 取整，
    # 整数坐标才与区块网格一一对应（这也是 kernel 里实际查询的用法）。
    for cx, cy in ((0, 0), (1, 0), (-1, 2)):
        grid = gen.generate_chunk(cx, cy)
        for lx, ly in ((0, 0), (5, 11), (CHUNK - 1, CHUNK - 1)):
            wx = cx * CHUNK + lx
            wy = cy * CHUNK + ly
            assert gen.get_tile(wx, wy) == grid[ly][lx], f"tile mismatch at {(cx, cy, lx, ly)}"
            assert gen.chunk_coord(wx, wy) == (cx, cy), "chunk_coord mismatch"
            assert gen.is_walkable(wx, wy) == (grid[ly][lx] in (FLOOR, ANOMALY))

    # 非负区块的小数坐标：落在同一格（0.5 偏移不改变格号）
    grid0 = gen.generate_chunk(0, 0)
    for lx, ly in ((0, 0), (7, 3), (CHUNK - 1, CHUNK - 1)):
        assert gen.get_tile(lx + 0.5, ly + 0.5) == grid0[ly][lx], "fractional lookup mismatch"

    # 远处坐标不抛异常，越界视为墙
    for wx, wy in ((-30.5, -12.0), (99.9, 240.0), (1e6, -1e6)):
        assert gen.get_tile(wx, wy) in (FLOOR, WALL, PILLAR, ANOMALY), "get_tile out of domain"

    # 出生点：3x3 全是地板
    spawn = gen.find_spawn(random.Random(5), near=(0.0, 0.0))
    assert all(gen.get_tile(spawn[0] + dx, spawn[1] + dy) == FLOOR
               for dy in (-1, 0, 1) for dx in (-1, 0, 1)), f"spawn not safe: {spawn}"

    # 固定尺寸关卡（README 记录的 BSP 路径）也要能出图
    level = gen.generate_level(32, 32)
    assert len(level) == 32 and len(level[0]) == 32, "generate_level shape wrong"
    assert gen.walkable_ratio(level) > 0.2, "generate_level too few walkable tiles"

    return (f"world-coordinate lookups self-consistent across chunks, "
            f"spawn 3x3 floor, fixed level {gen.walkable_ratio(level) * 100:.0f}% walkable")


# --------------------------------------------------------------------- 入口
def main() -> int:
    checks = [
        ("determinism", check_determinism),
        ("chunk connectivity", check_connectivity),
        ("world queries", check_world_queries),
    ]
    passed: list[str] = []
    for name, fn in checks:
        try:
            passed.append(fn())
        except Exception as exc:  # noqa: BLE001
            print(f"selfcheck FAIL: {name} -> {type(exc).__name__}: {exc}")
            return 1
    print("selfcheck ok: " + "; ".join(passed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
