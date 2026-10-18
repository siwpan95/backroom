# -*- coding: utf-8 -*-
"""backroom · 无尽阈室 —— 入口。

用法::

    python main.py                 正常运行
    python main.py --smoke         冒烟：跑几秒自动关闭（CI / 自检用）
    python main.py --shot          抓三张验证截图到 docs/ 后自动关闭
    python main.py --bench 5       5 秒基准
    python main.py auto            自动驾驶（录制 / 无人值守演示）
    python main.py seed1234        指定种子（同种子 = 同一张地图）

依赖：``pip install 3dworld``（渲染、材质、合批、相机、后处理全部来自它）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backroom.app import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
