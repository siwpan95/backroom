# backroom · 后室光线投射演示

> 仓库：<https://gitee.com/siwpan/backroom> ｜ 许可：MIT-0（MIT No Attribution）（见 [LICENSE](LICENSE)）

> 独立仓 siwpan/backroom（一仓一目录）。Backrooms（后室）风格的光线投射（raycaster）演示程序（pygame + numpy）。
> 发布面：gitee release `v1.0.0`（Windows 可执行程序，PyInstaller）。

## 功能

- pygame + numpy 实现的实时光线投射渲染（后室黄墙/荧光灯走廊风格）。
- 可选音频：`sounddevice` 实时音效（缺失时自动降级，不影响运行）。
- 多线程渲染辅助（threading）。

## 运行

```bash
pip install -r requirements.txt   # pygame、numpy；sounddevice 可选
python backrooms_raycaster.pyw
```

## 测试

- `test_debug.py` / `test_debug2.py` / `test_debug3.py` / `test_final.py`：光线投射与场景逻辑自检。

## 打包

- `backroom.spec`（PyInstaller，onedir）；调试版 `backroom-dbg.spec`。

## 谱系

源自 krieger-clone 光线投射实验线（现归档于本地 archive/notpython），本仓为独立演进版。

## 许可

MIT · Copyright (c) 2026 siwpan
