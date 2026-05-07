# -*- mode: python ; coding: utf-8 -*-
"""macOS .app 目录包（onedir + BUNDLE），便于封装 DMG 与系统集成。

双轨：``GITTOOL_SAUSAGE_INTERNAL=1`` 时打入仓库根 ``sausage_projects.yaml``，产物名为
``GitPullSwitchTool-Sausage``；否则公开版不内置该配置。
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
project_root = Path(SPECPATH).resolve().parent.parent
entry = project_root / "src" / "git_gui" / "main.py"
bundle_data = project_root / "src" / "git_gui" / "bundle_data"
root_sausage = project_root / "sausage_projects.yaml"
bundle_sausage = bundle_data / "sausage_projects.yaml"

sausage_internal = os.environ.get("GITTOOL_SAUSAGE_INTERNAL", "").strip().lower() in (
    "1",
    "true",
    "yes",
)

_bundle_datas: list[tuple[str, str]] = []
for p in sorted(bundle_data.iterdir()):
    if not p.is_file():
        continue
    if p.name == "sausage_projects.yaml":
        continue
    _bundle_datas.append((str(p), "bundle_data"))

if sausage_internal:
    if not root_sausage.is_file():
        raise FileNotFoundError(
            "香肠内部版打包：请在仓库根放置 sausage_projects.yaml 并设置 GITTOOL_SAUSAGE_INTERNAL=1"
        )
    _bundle_datas.append((str(root_sausage), "bundle_data"))

if not bundle_sausage.is_file():
    raise FileNotFoundError(f"缺少: {bundle_sausage}")

# Analysis 阶段未稳定解析入口脚本对 PySide6 的依赖时，显式收集 Qt 运行时与元数据，避免 .app 内缺库闪退。
_pyside6_datas, _pyside6_binaries, _pyside6_hidden = collect_all("PySide6")

app_base = "GitPullSwitchTool-Sausage" if sausage_internal else "GitPullSwitchTool"
bundle_identifier = (
    "com.sausagedev.gitpullswitchtool.sausage"
    if sausage_internal
    else "com.sausagedev.gitpullswitchtool"
)

icns_path = project_root / "assets" / "icon.icns"
icon_str = str(icns_path) if icns_path.is_file() else None

_keyring_hidden = list(collect_submodules("keyring"))

a = Analysis(
    [str(entry)],
    pathex=[str(project_root)],
    binaries=_pyside6_binaries,
    datas=_bundle_datas + _pyside6_datas,
    hiddenimports=(
        ["git", "yaml", "requests", "psutil"]
        + _pyside6_hidden
        + _keyring_hidden
    ),
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
    name=app_base,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch="universal2",
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
    upx=False,
    upx_exclude=[],
    name=app_base,
)
app = BUNDLE(
    coll,
    name=f"{app_base}.app",
    icon=icon_str,
    bundle_identifier=bundle_identifier,
    info_plist={
        "NSPrincipalClass": "NSApplication",
        "NSHighResolutionCapable": "True",
    },
)
