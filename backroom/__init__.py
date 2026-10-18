# -*- coding: utf-8 -*-
"""**backroom · 无尽阈室** —— 伪无限后室漫游（基于 3dworld 引擎重构）。

原项目是 pygame 2D 光线投射演示（1349 行，地图/渲染/实体/音频揉在一起）。
本版本按 **3dworld 分层范式**重构，只保留并强化其核心资产——**伪无限区块地图**，
渲染交由 3dworld 的三维管线承担。

分层
----
=================  ============================================  ==============
模块               职责                                          依赖
=================  ============================================  ==============
``mapgen``         伪无限区块地图（纯算法）                      仅标准库
``kernel``         玩家 / 层级 / 事件编排 / 寻路 / auto-pilot    3dworld 引擎件
``world``          场景渲染（PBR + 程序化材质 + 合批）           pyglet + 3dworld
``audio``          程序化音床                                    pyglet media
``app``            装配入口（HUD / 截图 / CLI）                  3dworld EngineApp
=================  ============================================  ==============

依赖方向：``app`` → ``world`` → ``kernel`` → ``mapgen``，反向禁止。

依赖
----
``pip install 3dworld``（PyPI）——3dworld 是本项目的**引擎库**，
不是"参考代码"：FSM / 事件总线 / 碰撞 / 程序化纹理 / 合批 / 渲染管线全部直接用它的。
"""
from .kernel import (CELL, EYE, LEVEL_NAMES, LEVELS, MAX_LEVEL, WALK, WALL_H,
                     BackroomKernel)
from .mapgen import (CHUNK, TILE_ANOMALY, TILE_FLOOR, TILE_PILLAR, TILE_WALL,
                     BackroomsGenerator, chunk_seed)

__version__ = '2.0.0'
__all__ = [
    '__version__',
    'BackroomKernel', 'BackroomsGenerator', 'chunk_seed',
    'CHUNK', 'CELL', 'EYE', 'WALK', 'WALL_H', 'MAX_LEVEL',
    'LEVELS', 'LEVEL_NAMES',
    'TILE_FLOOR', 'TILE_WALL', 'TILE_PILLAR', 'TILE_ANOMALY',
]
