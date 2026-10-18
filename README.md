# backroom · 无尽阈室（v2.0 · 3dworld 引擎重构版）

> 仓库：<https://gitee.com/siwpan/backroom> ｜ 许可：MIT-0（MIT No Attribution）（见 [LICENSE](LICENSE)）

Backrooms（后室）风格的**伪无限**第一人称漫游。
v1 是 pygame 2D 光线投射演示（1349 行单文件，现归档于 [`archive/`](archive/)）；
**v2 用 [3dworld](https://gitee.com/siwpan/3dworld) 引擎整体重构**——只保留并强化
原版的核心资产「伪无限区块地图」，渲染升级为真三维 PBR 管线。

## v2 相对 v1 的重构点

| | v1（pygame raycaster） | v2（3dworld 引擎） |
|---|---|---|
| 渲染 | 2D 光线投射（伪 3D） | 真三维 PBR + IBL + SSAO/Bloom/ACES 后处理 |
| 地图 | 伪无限 chunk（与渲染/实体耦合在单文件里） | 独立纯算法层 `backroom/mapgen.py`（零第三方依赖） |
| 碰撞 | 手写点检测 | `world3d.engine.physics` 分轴解算（沿墙滑动） |
| 状态机 | 无 | `world3d.engine.fsm.Machine`（settling→wandering→anomaly→descending） |
| 事件 | 无 | `world3d.engine.orchestration.Bus` 声明式级联（踏入异常→noclip→下潜→换层→灯闪→落地） |
| 材质 | 纯色 | `world3d.engine.proctex` 程序化 PBR（单黄壁纸/潮地毯/吸音板，零外部素材） |
| 墙体 | 逐格投射 | `world3d.engine.greedy_mesh` 贪心合批（一区块几十个 quad） |
| 灯光 | 无 | GPU 实例化灯管（1 次 draw call）+ 最近 4 盏点光 + Bloom 荧光溢出 |
| 音频 | sounddevice 实时合成 | 程序化音床（灯嗡/低频/远残响三层，WAV 缓存） |
| 工程化 | 单文件 | 分层包 + headless 单测（13 项）+ `--smoke/--shot/--bench` CLI |

## 分层

```
backroom/
  mapgen.py   伪无限区块地图（递归回溯迷宫+房间+异常区+连通兜底；仅标准库）
  kernel.py   玩家/层级/FSM/事件编排/寻路/auto-pilot（3dworld 引擎件）
  world.py    场景渲染（贪心合批+程序化材质+实例化灯管+流式区块）
  audio.py    程序化音床（三层合成，WAV 缓存）
  app.py      装配入口（EngineApp：HUD/截图/性能面板/CLI）
tests/test_kernel.py   13 项 headless 单测（连通性/确定性/碰撞/级联/伪无限）
archive/               v1 pygame 光线投射版（原样保留）
```

依赖方向：`app → world → kernel → mapgen`，反向禁止。
渲染层与逻辑层完全解耦：内核可 headless 跑（无窗口无 GL），auto-pilot
供录制与验收共用同一套逻辑。

## 运行

```bash
pip install 3dworld          # 唯一依赖（PyPI），渲染/材质/合批/相机/后处理全来自它
python main.py               # 正常运行
python main.py auto          # 自动驾驶（无人值守演示/录制）
python main.py seed1234      # 指定种子（同种子 = 同一张无限地图）
python main.py --smoke       # 冒烟：几秒自动关闭
python main.py --shot        # 抓三张验证截图到 docs/
python main.py --bench 5     # 5 秒基准
```

操作：`WASD` 走　拖拽转视角　`SHIFT` 疾走　`A` 自动驾驶　`T` 下潜一层　
`R` 换地图　`SPACE` 暂停　`F1` HUD　`F2` 性能面板　`ESC` 退出

## 玩法（仅地图，无实体）

- **伪无限**：世界按 24×24 格区块无限延展，走多少生成多少，离开视野即卸载；
- **层级下潜**：离原点越远层级越深（Level 0 大厅 → 4 深处），配色/雾距/灯密度递进；
- **noclip**：踏入异常区（潮渍格）触发级联——下潜到下一层并传送到未探索区块；
- **灯闪**：每次换层荧光灯抽搐 1.6 秒（点光亮度抖动）。

## 测试

```bash
.venv/Scripts/python -m tests.test_kernel    # 13 项 headless 单测
```

钉住的行为契约：同 seed 同地图、区块内可走格全连通、跨区块查询连续、
碰撞不穿墙、异常级联走完整条链、noclip 必有位移、auto-pilot 150s 必须走出
出生区块、轨迹确定性（录制可复现的前提）。

## 打包

```bash
.venv/Scripts/python -m pip install pyinstaller
python scripts/build_exe.py                  # onedir → dist/backroom/backroom.exe
```

零外部素材（材质与音床都是运行时程序化生成），不需要 `--add-data` 任何资源。
产物约 23MB（onedir）；分发时整目录压成一个 zip（实测 11.6MB，62 文件）。
发布面：gitee release `v2.0.0`（Windows 可执行程序 + SHA256SUMS）。

## 谱系

- v1：源自 krieger-clone 光线投射实验线（归档于 `archive/`）。
- v2：受 [3dworld](https://gitee.com/siwpan/3dworld)（siwpan）驱动——
  其 `liminall`（阈廊）验证了"后室题材 + 3dworld 分层"可行，
  本仓将「伪无限地图」这一差异化资产正式接入该引擎。

## 许可

MIT-0 · Copyright (c) 2026 siwpan
