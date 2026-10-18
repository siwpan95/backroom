# -*- coding: utf-8 -*-
"""backroom 内核单测（headless，不需要窗口 / GL）。

钉住的是**行为契约**，不是实现细节：

1. 同 seed 必须生成同一张图（可复现性是录制与验收的前提）；
2. 每个区块内部地板必须全连通（孤岛会让玩家被封死）；
3. 世界查询跨区块连续、越界不抛异常；
4. 碰撞不能穿墙（这是"能走"的底线）；
5. 事件级联必须走完整条链（踏入异常 → 下潜 → 换层 → 灯闪 → 落地）；
6. auto-pilot 必须真的走出出生区块（否则"伪无限"名不副实）。
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backroom.kernel import BackroomKernel, CELL, CHUNK, MAX_LEVEL, TILE_WALL  # noqa: E402
from backroom.mapgen import (BackroomsGenerator, TILE_ANOMALY,  # noqa: E402
                             TILE_FLOOR, TILE_PILLAR, chunk_seed,
                             ensure_connected)

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# ---------------------------------------------------------------- 地图层
@test
def test_chunk_seed_deterministic():
    """区块子种子必须跨进程稳定（原实现用 hash(tuple) 是不保证的）。"""
    assert chunk_seed(3, -7, 42) == chunk_seed(3, -7, 42)
    assert chunk_seed(3, -7, 42) != chunk_seed(-7, 3, 42)


@test
def test_same_seed_same_map():
    a = BackroomsGenerator(seed=1234)
    b = BackroomsGenerator(seed=1234)
    assert a.generate_chunk(0, 0) == b.generate_chunk(0, 0)
    assert a.generate_chunk(2, -3) == b.generate_chunk(2, -3)
    assert BackroomsGenerator(seed=1235).generate_chunk(0, 0) != a.generate_chunk(0, 0)


@test
def test_chunk_fully_connected():
    """区块内所有地板必须互相可达——有孤岛就意味着玩家可能被封死在里面。"""
    for seed in (7, 99, 20261019):
        g = BackroomsGenerator(seed=seed)
        grid = g.generate_chunk(0, 0)
        # 可走 = 地板 **或** 异常区（异常格能踏进去，正是 noclip 的入口）
        floors = {(x, y) for y in range(CHUNK) for x in range(CHUNK)
                  if grid[y][x] in (TILE_FLOOR, TILE_ANOMALY)}
        assert floors, f'seed={seed}: 没有地板'
        start = min(floors)          # 用确定顺序，别依赖 set 迭代顺序
        seen, stack = {start}, [start]
        while stack:
            x, y = stack.pop()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in floors and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        orphan = floors - seen
        assert not orphan, f'seed={seed}: 孤立地板 {sorted(orphan)[:5]}'


@test
def test_world_query_cross_chunk():
    """跨区块查询连续、越界一律当墙、不抛异常。"""
    g = BackroomsGenerator(seed=2026)
    for wx in (-80.5, -1.0, 0.0, 35.5, 200.25):
        for wz in (-40.0, 7.5, 180.0):
            assert g.get_tile(wx, wz) in (TILE_FLOOR, TILE_WALL, TILE_PILLAR, TILE_ANOMALY)
    assert g.get_tile(1e6, 1e6) == TILE_WALL


@test
def test_fixed_level_usable():
    """原实现的 generate_level 调用未定义的 _divide 会 AttributeError，这里必须可用。"""
    g = BackroomsGenerator(seed=5)
    lvl = g.generate_level(32, 32)
    assert len(lvl) == 32 and len(lvl[0]) == 32
    assert g.walkable_ratio(lvl) > 0.25


# ---------------------------------------------------------------- 内核层
@test
def test_kernel_starts_in_settling():
    k = BackroomKernel(seed=1)
    assert k.fsm.current == 'settling', k.fsm.current


@test
def test_kernel_enters_wandering():
    """settling 有时长：2.5s 后应自动进入 wandering。"""
    k = BackroomKernel(seed=2)
    for _ in range(200):
        k.step(1 / 60.0)
    assert k.fsm.current == 'wandering', k.fsm.current


@test
def test_collision_never_enters_wall():
    """沿墙滑动的底线：任何时刻玩家中心都不能落在实心格里。"""
    k = BackroomKernel(seed=3)
    k.auto = True
    for _ in range(3000):
        k.step(1 / 60.0)
        assert k.tile_at(k.x, k.z) != TILE_WALL, f'穿墙于 ({k.x:.2f},{k.z:.2f})'


@test
def test_anomaly_triggers_full_cascade():
    """踏入异常格必须走完整条级联：发现 → noclip → 下潜 → 换层 → 灯闪 → 落地。"""
    k = BackroomKernel(seed=4)
    # 直接把玩家放到一个异常格上
    target = None
    gx, gy = k.nearest_open(k.x, k.z)
    for r in range(1, 40):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                tx, ty = gx + dx, gy + dy
                if k.tile_at((tx + 0.5) * CELL, (ty + 0.5) * CELL) == TILE_ANOMALY:
                    target = (tx, ty)
                    break
            if target:
                break
        if target:
            break
    assert target is not None, '地图里没有异常格'
    k.x, k.z = (target[0] + 0.5) * CELL, (target[1] + 0.5) * CELL
    k.fsm.fire('entered', 0.0)
    lv0 = k.level
    k.step(1 / 60.0)
    kinds = {e for _, e in k.bus.log}
    for ev in ('anomaly_found', 'noclip', 'descend', 'level_change',
               'lights_flicker', 'landed'):
        assert ev in kinds, f'级联缺 {ev}（实到 {sorted(kinds)}）'
    assert k.level == min(lv0 + 1, MAX_LEVEL)
    assert k.descents >= 1


@test
def test_noclip_teleports():
    """noclip 必须位移——只改层级会让玩家钉在原地反复下潜。"""
    k = BackroomKernel(seed=5)
    k.fsm.fire('entered', 0.0)
    x0, z0 = k.x, k.z
    k.bus.emit('noclip')
    assert math.hypot(k.x - x0, k.z - z0) > CELL, 'noclip 没有位移'


@test
def test_autopilot_escapes_spawn_chunk():
    """伪无限的名副其实：auto-pilot 必须走出出生区块。"""
    k = BackroomKernel(seed=20261019)
    k.auto = True
    for _ in range(9000):          # 150s
        k.step(1 / 60.0)
    assert len(k.chunks_seen) >= 3, f'150s 只探索了 {len(k.chunks_seen)} 个区块'


@test
def test_level_monotonic_and_bounded():
    k = BackroomKernel(seed=6)
    k.auto = True
    prev = 0
    for _ in range(9000):
        k.step(1 / 60.0)
        assert 0 <= k.level <= MAX_LEVEL
        assert k.level >= prev      # 层级只增不减
        prev = k.level


@test
def test_kernel_headless_deterministic():
    """同 seed 跑同样的输入，轨迹必须一致（录制可复现的前提）。"""
    def run(seed):
        k = BackroomKernel(seed=seed)
        k.auto = True
        for _ in range(1200):
            k.step(1 / 60.0)
        return (round(k.x, 6), round(k.z, 6), round(k.dist, 6), k.descents)
    assert run(77) == run(77)
    assert run(77) != run(78)


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f'  PASS  {fn.__name__}')
        except AssertionError as e:
            failed += 1
            print(f'  FAIL  {fn.__name__}: {e}')
        except Exception as e:                      # noqa: BLE001
            failed += 1
            print(f'  ERROR {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(TESTS) - failed}/{len(TESTS)} passed')
    if failed == 0:
        print('ALL_BACKROOM_TESTS_PASSED')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
