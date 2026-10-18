# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.0] - 2026-10-19

**引擎化重构**：由 pygame 2D 光线投射演示，改为基于 [3dworld](https://gitee.com/siwpan/3dworld)
引擎（PyPI：``pip install 3dworld``）的伪无限三维后室漫游。

### Added

- `backroom/mapgen.py`：独立纯地图层（仅标准库）——伪无限 24×24 区块、递归回溯迷宫、
  房间/孤立柱/异常区、`ensure_connected()` 可走性连通兜底、BSP 固定关卡。
- `backroom/kernel.py`：玩家 / 层级下潜（Level 0→4）/ FSM 状态机 / 事件编排 / BFS 寻路 / auto-pilot。
- `backroom/world.py`：贪心合批建墙 + 程序化 PBR 材质（零外部素材）+ 灯管 GPU 实例化
  + PBR/IBL 渲染 + Bloom/SSAO/ACES 后处理（顺序由帧图钉住）+ 区块流式装卸。
- `backroom/audio.py`：程序化音床三层（荧光灯嗡 / 低频嗡鸣 / 远处残响），WAV 缓存。
- `backroom/app.py`：装配层（继承 `world3d.engine.app.EngineApp`）——HUD / 性能面板 /
  `--smoke` `--shot` `--bench` CLI。
- `tests/test_kernel.py`：13 项 headless 单测。

### Changed

- 渲染：2D 光线投射 → 真三维 PBR 管线。
- 依赖：pygame + numpy + sounddevice → **仅 `3dworld`**。
- 结构：1349 行单文件 → `mapgen / kernel / world / audio / app` 五层包
  （依赖方向 `app → world → kernel → mapgen`，反向禁止）。
- v1 的 pygame 实现移入 `archive/` 保留（未删除）。

### Fixed

- `generate_level` 调用**未定义**的 `_divide`（必然 `AttributeError`）——补齐 BSP 实现。
- 区块子种子用 `hash((cx, cy, seed))`，不保证跨进程稳定 → 改为显式整数混合，
  锁死「同 seed 同地图」。
- 异常区染色会切断走廊通路，且角落会生成永远走不到的孤立格 → 最大连通域 L 形挖路兜底。
- noclip 只改层级不位移 → 玩家原地反复下潜、伪无限地图永远走不出去 → 增加传送位移。

### Verified

- `python -m tests.test_kernel` **13/13 通过**。
- `python main.py --smoke` EXIT_OK；`--shot` 产出三张验证截图。
- `python main.py --bench 5`：**117.4 fps** @720p（vsync off），jank 0%。

## [1.0.0] - 2026-08-27

### Added

- 首个发行版：Windows 可执行程序（PyInstaller，Python 3.14）。
- 发布面：gitee [siwpan/backroom](https://gitee.com/siwpan/backroom) release `v1.0.0`（后室 v1.0.0）。