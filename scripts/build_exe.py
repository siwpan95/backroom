# -*- coding: utf-8 -*-
"""打包 backroom 为 Windows 可执行程序（PyInstaller）。

前置（在本项目 venv 里）::

    pip install pyinstaller

用法::

    python scripts/build_exe.py            # 打包（onedir，启动快于 onefile）

产物 ``dist/backroom/backroom.exe``。

选型说明
--------
- **onedir 而非 onefile**：onefile 每次启动都要把整个包解压到临时目录（几百 MB 写入），
  冷启动慢；onedir 直接加载，体感接近原生。分发时把整个目录压成一个 zip 即可
  （Gitee 附件名不能带路径分隔符，但 zip 内部保留目录结构，没有这个问题）。
- **console 而非 windowed**：本项目有 ``--smoke / --shot / --bench`` 这类 CLI，
  控制台输出本身就是验收证据；想要无控制台时用 ``--windowed`` 参数覆盖。
- **零外部素材**：材质（proctex）与音床（audio）都是运行时程序化生成的，
  所以不需要 ``--add-data`` 任何资源文件——这也是它比一般游戏好打包的原因。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, 'main.py')
DIST = os.path.join(ROOT, 'dist')
WORK = os.path.join(ROOT, 'build', 'pyinstaller')
NAME = 'backroom'


def build(windowed=False, clean=True):
    cmd = [sys.executable, '-m', 'PyInstaller',
           '--noconfirm', '--onedir', f'--name={NAME}',
           f'--distpath={DIST}', f'--workpath={WORK}',
           f'--specpath={os.path.join(ROOT, "build")}',
           '--exclude-module=tkinter',
           '--exclude-module=PyQt5',
           '--exclude-module=IPython',
           ]
    if windowed:
        cmd.append('--windowed')
    if clean:
        cmd.append('--clean')
    cmd.append(ENTRY)
    print('[build]', ' '.join(cmd[:6]), '...')
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        print('[build] FAILED rc=%d' % r.returncode)
        return r.returncode
    exe = os.path.join(DIST, NAME, f'{NAME}.exe')
    if os.path.isfile(exe):
        print('[build] OK ->', exe, '%.1f MB' % (os.path.getsize(exe) / 1048576))
    return 0


def main():
    ap = argparse.ArgumentParser(description='打包 backroom 为 Windows 可执行程序')
    ap.add_argument('--windowed', action='store_true', help='不显示控制台窗口')
    ap.add_argument('--no-clean', action='store_true', help='跳过清理（增量构建）')
    a = ap.parse_args()
    return build(windowed=a.windowed, clean=not a.no_clean)


if __name__ == '__main__':
    raise SystemExit(main())
