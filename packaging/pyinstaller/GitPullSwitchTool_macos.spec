# -*- mode: python ; coding: utf-8 -*-
"""macOS .app 目录包（onedir + BUNDLE），便于封装 DMG 与系统集成。

未在此 spec 中固定 universal2：在 Intel 与 Apple Silicon 上分别构建可在对应架构运行；
若需 universal2，需在支持双架构的 Python 解释器上执行 PyInstaller 并设置 target_arch。
"""
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH).resolve().parent.parent
entry = project_root / "src" / "git_gui" / "main.py"
bundle_data = project_root / "src" / "git_gui" / "bundle_data"
icns_path = project_root / "assets" / "icon.icns"
icon_str = str(icns_path) if icns_path.is_file() else None

a = Analysis(
    [str(entry)],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(bundle_data), "bundle_data")],
    hiddenimports=["git", "yaml", "requests", "psutil"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GitPullSwitchTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_str,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GitPullSwitchTool",
)
app = BUNDLE(
    coll,
    name="GitPullSwitchTool.app",
    icon=icon_str,
    bundle_identifier="com.sausagedev.gitpullswitchtool",
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": "True",
    },
)
