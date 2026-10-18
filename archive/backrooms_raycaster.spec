# -*- mode: python ; coding: utf-8 -*-
# 入口脚本按 spec 所在目录推导（原为本机一条已失效的绝对路径，见硬编码门禁清单；
# 本仓现行源文件是同目录的 backrooms_raycaster.pyw，与本仓 backroom.spec 口径一致）
import os


a = Analysis(
    [os.path.join(SPECPATH, 'backrooms_raycaster.pyw')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='backrooms_raycaster',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
