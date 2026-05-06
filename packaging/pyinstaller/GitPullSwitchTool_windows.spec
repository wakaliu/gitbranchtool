# -*- mode: python ; coding: utf-8 -*-
"""Windows onefile 可执行文件构建说明。

双轨打包（环境变量 ``GITTOOL_SAUSAGE_INTERNAL``）：
- 未设置 / 0：公开版，**不**内置 ``sausage_projects.yaml``（内部克隆页签不出现，除非用户在 exe 旁自行放该文件）。
- 1：香肠内部版，**必须**在仓库根存在本地 ``sausage_projects.yaml``（勿提交 Git）并打入 ``bundle_data/``。

datas 与 ``runtime_paths.get_embedded_assets_dir()`` 约定一致。
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

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
        if sausage_internal:
            continue
        continue
    _bundle_datas.append((str(p), "bundle_data"))

if sausage_internal:
    if not root_sausage.is_file():
        raise FileNotFoundError(
            "香肠内部版打包：请先在仓库根目录放置 sausage_projects.yaml（勿提交 Git），"
            "并设置环境变量 GITTOOL_SAUSAGE_INTERNAL=1 后再执行 PyInstaller。"
        )
    _bundle_datas.append((str(root_sausage), "bundle_data"))

if not bundle_sausage.is_file():
    raise FileNotFoundError(f"缺少模板文件: {bundle_sausage}（仓库应保留 bundle_data 内占位，公开版打包不嵌入该文件）")

exe_base_name = "GitPullSwitchTool-Sausage" if sausage_internal else "GitPullSwitchTool"

icon_path = project_root / "assets" / "icon.ico"
icon_str = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(entry)],
    pathex=[str(project_root)],
    binaries=[],
    datas=_bundle_datas,
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
    name=exe_base_name,
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
