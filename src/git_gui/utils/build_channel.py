"""识别当前运行包为公开版或香肠内部版（与 PyInstaller 产物名一致）。"""
from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path


class BuildChannel(str, Enum):
    """分发渠道。"""

    PUBLIC = "public"
    SAUSAGE = "sausage"


def is_sausage_build() -> bool:
    """可执行文件名或 .app 包名是否含 Sausage。"""
    return get_build_channel() == BuildChannel.SAUSAGE


def get_build_channel() -> BuildChannel:
    """根据 ``sys.executable`` 与 macOS bundle 路径判断渠道。"""
    exe = Path(sys.executable).resolve()
    name = exe.name
    if "Sausage" in name:
        return BuildChannel.SAUSAGE
    if sys.platform == "darwin" and exe.parent.name == "MacOS":
        app_name = exe.parent.parent.name
        if "Sausage" in app_name:
            return BuildChannel.SAUSAGE
    return BuildChannel.PUBLIC
