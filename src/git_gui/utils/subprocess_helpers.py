"""subprocess 与平台相关的通用参数。

Windows 上 GUI 应用通过 subprocess 启动 git.exe 时，默认会分配可见控制台，
表现为黑色命令行窗口闪现；传入 CREATE_NO_WINDOW 后子进程无独立控制台窗口。

macOS 上从 .app / Finder 启动的 GUI 进程 PATH 通常不含 Homebrew 目录，会导致
``git-lfs: command not found``（LFS 仓库在 reset/checkout/fetch 时失败）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


def subprocess_hide_console_kwargs() -> dict[str, Any]:
    """供 subprocess.run / Popen 解包使用的关键字参数。

    Returns:
        在 Windows 上为 ``{"creationflags": subprocess.CREATE_NO_WINDOW}``，
        其他平台返回空字典（不影响行为）。
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _darwin_git_child_environ() -> Optional[dict[str, str]]:
    """为子进程构造含常见 CLI 安装路径的 PATH，便于找到 git-lfs；非 macOS 返回 None。"""
    if sys.platform != "darwin":
        return None
    env = dict(os.environ)
    prefixes: list[str] = []
    for p in (
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
        str(Path.home() / ".local" / "bin"),
    ):
        if Path(p).is_dir() and p not in prefixes:
            prefixes.append(p)
    extra = os.environ.get("GITTOOL_PATH_PREFIX", "").strip()
    if extra:
        for p in extra.split(os.pathsep):
            p = p.strip()
            if p and Path(p).is_dir() and p not in prefixes:
                prefixes.insert(0, p)
    if not prefixes:
        return None
    cur = env.get("PATH", "")
    env["PATH"] = os.pathsep.join(prefixes + ([cur] if cur else []))
    return env


def subprocess_git_command_kwargs() -> dict[str, Any]:
    """调用系统 ``git`` 子进程时与 ``subprocess.run`` 合并的关键字（含 Windows 无窗口与 macOS PATH）。"""
    kw: dict[str, Any] = dict(subprocess_hide_console_kwargs())
    env = _darwin_git_child_environ() or dict(os.environ)
    env["GIT_FLUSH"] = "1"
    env["GIT_PROGRESS_DELAY"] = "0"
    kw["env"] = env
    return kw
