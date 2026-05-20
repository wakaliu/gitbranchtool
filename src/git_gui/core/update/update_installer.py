"""下载更新包并在应用退出后执行安装/替换。"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import requests
from requests.exceptions import RequestException

from ...utils.build_channel import is_sausage_build
from ...utils.runtime_paths import get_user_data_dir
from ...utils.subprocess_helpers import subprocess_hide_console_kwargs
from .release_checker import UpdateOffer

def get_updates_dir() -> Path:
    """用户目录下存放更新包与脚本的文件夹。"""
    path = get_user_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_update(
    offer: UpdateOffer,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """流式下载 Release 资产到本地。

    Args:
        offer: 更新信息。
        on_progress: ``(downloaded_bytes, total_bytes)``，total 为 0 表示未知。

    Returns:
        本地文件路径。

    Raises:
        RequestException: 下载失败。
        OSError: 磁盘写入失败。
    """
    dest = get_updates_dir() / offer.asset_name
    if dest.exists():
        dest.unlink()

    from ...utils.github_issue import GitHubIssueReporter

    headers = {"Accept": "application/octet-stream"}
    token = GitHubIssueReporter()._effective_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with requests.get(offer.download_url, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or offer.asset_size or 0)
        downloaded = 0
        with open(dest, "wb") as out:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                out.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    return dest


def _write_windows_portable_bat(
    bat_path: Path,
    pid: int,
    source_exe: Path,
    target_exe: Path,
) -> None:
    content = f"""@echo off
:wait_loop
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)
copy /Y "{source_exe}" "{target_exe}"
start "" "{target_exe}"
"""
    bat_path.write_text(content, encoding="utf-8")


def _write_macos_apply_script(
    script_path: Path,
    dmg_path: Path,
    target_app: Path,
    open_after: Path,
) -> None:
    content = f"""#!/bin/bash
set -euo pipefail
DMG="{dmg_path}"
TARGET="{target_app}"
OPEN_APP="{open_after}"
MOUNT="$(hdiutil attach "$DMG" -nobrowse -quiet | tail -1 | awk '{{print $NF}}')"
cleanup() {{
  hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
}}
trap cleanup EXIT
SRC_APP="$(find "$MOUNT" -maxdepth 1 -name '*.app' | head -1)"
if [ -z "$SRC_APP" ]; then
  echo "No .app in DMG" >&2
  exit 1
fi
ditto "$SRC_APP" "$TARGET"
open "$OPEN_APP"
"""
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)


def _macos_target_app_bundle() -> Path:
    """当前或默认 Applications 下的 .app 路径。"""
    exe = Path(sys.executable).resolve()
    if exe.parent.name == "MacOS":
        return exe.parent.parent
    name = "GitPullSwitchTool-Sausage.app" if is_sausage_build() else "GitPullSwitchTool.app"
    return Path("/Applications") / name


def launch_apply_after_quit(package_path: Path) -> None:
    """生成退出后安装脚本并交由系统执行；调用方应随后 ``quit`` 应用。

    Args:
        package_path: 已下载的 Setup.exe 或 .dmg。

    Raises:
        RuntimeError: 平台不支持或启动脚本失败。
        OSError: 写入脚本失败。
    """
    hide = subprocess_hide_console_kwargs()
    pid = os.getpid()

    if sys.platform == "win32":
        if package_path.suffix.lower() == ".exe":
            subprocess.Popen(
                [
                    str(package_path),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/CLOSEAPPLICATIONS",
                ],
                **hide,
            )
            return
        target = Path(sys.executable).resolve()
        bat = get_updates_dir() / "apply_update.bat"
        _write_windows_portable_bat(bat, pid, package_path, target)
        subprocess.Popen(["cmd", "/c", str(bat)], **hide)
        return

    if sys.platform == "darwin":
        target_app = _macos_target_app_bundle()
        script = get_updates_dir() / "apply_update.sh"
        _write_macos_apply_script(script, package_path.resolve(), target_app, target_app)
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
        return

    raise RuntimeError("当前平台不支持自动安装")


def wait_pid_exit(pid: int, timeout_seconds: float = 60.0) -> None:
    """轮询直到进程结束（供测试或脚本使用）。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)
