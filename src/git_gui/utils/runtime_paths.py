"""开发与 PyInstaller 冻结环境下的路径解析。

冻结后只读资源位于 sys._MEIPASS；可写配置与日志必须落在用户目录，
避免安装到 Program Files 或只读卷时无法保存设置或写日志。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_FOLDER_NAME = "GitPullSwitchTool"


def is_pyinstaller_bundle() -> bool:
    """当前进程是否由 PyInstaller 打包启动。"""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def get_executable_dir() -> Path:
    """可执行文件所在目录（onefile 下为 exe 所在目录）。"""
    return Path(sys.executable).resolve().parent


def get_repository_root() -> Path:
    """源码仓库根目录（layout: 仓库根/src/git_gui/...）。"""
    return Path(__file__).resolve().parents[3]


def get_embedded_assets_dir() -> Path:
    """随应用分发的只读默认配置等资源目录。"""
    if is_pyinstaller_bundle():
        return Path(sys._MEIPASS) / "bundle_data"
    return Path(__file__).resolve().parents[1] / "bundle_data"


def get_user_data_dir() -> Path:
    """用户可写数据根目录（配置持久化、日志等）。"""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / _APP_FOLDER_NAME
    elif os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        base = Path(local) / _APP_FOLDER_NAME
    else:
        base = Path.home() / ".local" / "share" / _APP_FOLDER_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_config_file_path() -> Path:
    """config.yaml 的绝对路径：冻结版写入用户目录；开发版写入仓库根。"""
    if is_pyinstaller_bundle():
        return get_user_data_dir() / "config.yaml"
    return get_repository_root() / "config.yaml"


def get_logs_dir() -> Path:
    """日志目录：冻结版固定到用户目录，避免工作目录变化导致日志散落。"""
    if is_pyinstaller_bundle():
        log_dir = get_user_data_dir() / "logs"
    else:
        log_dir = get_repository_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_application_root_for_diagnostics() -> Path:
    """诊断日志中展示的“应用根”路径，便于区分开发目录与安装目录。"""
    if is_pyinstaller_bundle():
        return get_executable_dir()
    return get_repository_root()
