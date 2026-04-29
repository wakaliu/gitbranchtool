"""subprocess 与平台相关的通用参数。

Windows 上 GUI 应用通过 subprocess 启动 git.exe 时，默认会分配可见控制台，
表现为黑色命令行窗口闪现；传入 CREATE_NO_WINDOW 后子进程无独立控制台窗口。
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any


def subprocess_hide_console_kwargs() -> dict[str, Any]:
    """供 subprocess.run / Popen 解包使用的关键字参数。

    Returns:
        在 Windows 上为 ``{"creationflags": subprocess.CREATE_NO_WINDOW}``，
        其他平台返回空字典（不影响行为）。
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
