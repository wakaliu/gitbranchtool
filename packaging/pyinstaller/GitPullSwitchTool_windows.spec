# -*- mode: python ; coding: utf-8 -*-
"""Windows onefile 可执行文件构建说明。

datas 中的 bundle_data 与 runtime_paths.get_embedded_assets_dir() 约定一致。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
project_root = Path(SPECPATH).resolve().parent.parent
entry = project_root / "src" / "git_gui" / "main.py"
bundle_data = project_root / "src" / "git_gui" / "bundle_data"
icon_path = project_root / "assets" / "icon.ico"
icon_str = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(entry)],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(bundle_data), "bundle_data")],
    hiddenimports=["git", "yaml", "requests", "psutil"]
    + collect_submodules("keyring"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="GitPullSwitchTool",
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
    icon=icon_str,
)
