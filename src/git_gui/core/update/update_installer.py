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

from ...config.constants import APP_VERSION
from ...utils.build_channel import is_sausage_build
from ...utils.runtime_paths import get_user_data_dir
from ...utils.subprocess_helpers import subprocess_hide_console_kwargs
from .release_checker import UpdateOffer

_DOWNLOAD_CONNECT_TIMEOUT = 30
_DOWNLOAD_READ_TIMEOUT = 300
_DOWNLOAD_PROGRESS_STEP_BYTES = 512 * 1024

def get_updates_dir() -> Path:
    """用户目录下存放更新包与脚本的文件夹。"""
    path = get_user_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


class UpdateDownloadCancelled(Exception):
    """用户取消下载。"""


def download_update(
    offer: UpdateOffer,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
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

    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": f"GitPullSwitchTool-Update/{APP_VERSION}",
    }
    token = GitHubIssueReporter()._effective_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if on_progress:
        on_progress(0, int(offer.asset_size or 0))

    with requests.get(
        offer.download_url,
        headers=headers,
        stream=True,
        timeout=(_DOWNLOAD_CONNECT_TIMEOUT, _DOWNLOAD_READ_TIMEOUT),
        allow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or offer.asset_size or 0)
        if on_progress:
            on_progress(0, total)
        downloaded = 0
        last_reported = 0
        try:
            with open(dest, "wb") as out:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if should_cancel and should_cancel():
                        raise UpdateDownloadCancelled("用户已取消下载")
                    if not chunk:
                        continue
                    out.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and (
                        downloaded == 0
                        or (total > 0 and downloaded >= total)
                        or downloaded - last_reported >= _DOWNLOAD_PROGRESS_STEP_BYTES
                    ):
                        on_progress(downloaded, total)
                        last_reported = downloaded
            if on_progress and downloaded > last_reported:
                on_progress(downloaded, total)
        except UpdateDownloadCancelled:
            if dest.exists():
                dest.unlink()
            raise
    return dest


def _curl_executable() -> str:
    """macOS 自带 curl 路径；打包版 GUI 进程 PATH 可能不含 curl。"""
    bundled = Path("/usr/bin/curl")
    if bundled.is_file():
        return str(bundled)
    return "curl"


def probe_release_asset_size_curl(download_url: str) -> int:
    """用 curl HEAD 获取 Content-Length（字节），避免更新流程中调用 requests/SSL。"""
    from ...utils.github_issue import GitHubIssueReporter

    cmd = [
        _curl_executable(),
        "-fILs",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}\n%header{content-length}",
        "-A",
        f"GitPullSwitchTool-Update/{APP_VERSION}",
    ]
    token = GitHubIssueReporter()._effective_token()
    if token:
        cmd.extend(["-H", f"Authorization: Bearer {token}"])
    cmd.append(download_url)
    hide = subprocess_hide_console_kwargs()
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            **hide,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    lines = (completed.stdout or "").strip().splitlines()
    if not lines or lines[0] != "200":
        return 0
    if len(lines) >= 2 and lines[1].strip().isdigit():
        try:
            return max(0, int(lines[1].strip()))
        except (TypeError, ValueError):
            pass
    return _probe_content_length_from_curl_headers(download_url, token)


def _probe_content_length_from_curl_headers(download_url: str, token: str | None) -> int:
    """旧版 curl 无 ``%header{content-length}`` 时从响应头解析。"""
    import re

    cmd = [
        _curl_executable(),
        "-fLs",
        "-o",
        "/dev/null",
        "-D",
        "-",
        "-A",
        f"GitPullSwitchTool-Update/{APP_VERSION}",
    ]
    if token:
        cmd.extend(["-H", f"Authorization: Bearer {token}"])
    cmd.append(download_url)
    hide = subprocess_hide_console_kwargs()
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            **hide,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if completed.returncode != 0:
        return 0
    found = 0
    for line in (completed.stdout or "").splitlines():
        m = re.match(r"^[Cc]ontent-[Ll]ength:\s*(\d+)\s*$", line.strip())
        if m:
            found = max(found, int(m.group(1)))
    return found


def start_curl_download(
    offer: UpdateOffer,
    *,
    resume: bool = False,
) -> tuple[subprocess.Popen, Path]:
    """在主线程启动 ``curl`` 下载（避免 ``requests``/SSL 在 Qt 线程池内崩溃）。

    Returns:
        ``(子进程, 目标文件路径)``。
    """
    from ...utils.github_issue import GitHubIssueReporter

    dest = get_updates_dir() / offer.asset_name
    partial = resume and dest.is_file() and dest.stat().st_size > 0
    if dest.exists() and not partial:
        dest.unlink()

    cmd = [
        _curl_executable(),
        "-fL",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        str(_DOWNLOAD_CONNECT_TIMEOUT),
        "--max-time",
        "7200",
        # 连续 5 分钟平均低于 1KB/s 视为停滞；应用层另有 90s 无增长断点续传
        "--speed-time",
        "300",
        "--speed-limit",
        "1024",
        "-A",
        f"GitPullSwitchTool-Update/{APP_VERSION}",
        "-o",
        str(dest),
    ]
    if partial:
        cmd.extend(["-C", "-"])
    token = GitHubIssueReporter()._effective_token()
    if token:
        cmd.extend(["-H", f"Authorization: Bearer {token}"])
    cmd.append(offer.download_url)

    hide = subprocess_hide_console_kwargs()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        **hide,
    )
    return proc, dest


def terminate_curl_download(proc: subprocess.Popen) -> None:
    """终止进行中的 curl 下载子进程。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def read_curl_download_error(proc: subprocess.Popen) -> str:
    """读取 curl 失败时的 stderr 摘要。"""
    if proc.stderr is None:
        return f"curl 退出码 {proc.returncode}"
    try:
        raw = proc.stderr.read()
        text = (raw.decode("utf-8", errors="replace") if raw else "").strip()
    except OSError:
        text = ""
    if text:
        line = text.splitlines()[-1]
        return line[:500]
    return f"curl 退出码 {proc.returncode}"


def windows_installed_exe_path() -> Path:
    """Inno 默认安装目录下的主程序路径（与 ``*.iss`` 中 DefaultDirName 一致）。"""
    program_files = Path(
        os.environ.get("ProgramFiles") or r"C:\Program Files"
    )
    if is_sausage_build():
        return program_files / "GitPullSwitchTool-Sausage" / "GitPullSwitchTool-Sausage.exe"
    return program_files / "GitPullSwitchTool" / "GitPullSwitchTool.exe"


def _write_windows_setup_bat(
    bat_path: Path,
    pid: int,
    setup_exe: Path,
    launch_exe: Path,
) -> None:
    """等待主进程退出后静默安装，并在完成后启动已安装目录中的 exe。"""
    setup = str(setup_exe.resolve())
    launch = str(launch_exe.resolve())
    content = f"""@echo off
:wait_loop
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)
start "" /wait "{setup}" /VERYSILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS /NORESTARTAPPLICATIONS
if exist "{launch}" (
    start "" "{launch}"
)
"""
    bat_path.write_text(content, encoding="utf-8")


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


def _macos_running_app_bundle() -> Path:
    """当前进程所在的 .app 路径（非 bundle 运行时回退到「应用程序」默认名）。"""
    exe = Path(sys.executable).resolve()
    if exe.parent.name == "MacOS":
        return exe.parent.parent
    name = "GitPullSwitchTool-Sausage.app" if is_sausage_build() else "GitPullSwitchTool.app"
    return Path("/Applications") / name


def parse_hdiutil_attach_mount_point(attach_output: str) -> str:
    """从 ``hdiutil attach`` 文本输出解析 ``/Volumes/...`` 挂载点。

    APFS 卷名可能含空格（如 ``GitPullSwitchTool 4``），不可用 ``awk '{print $NF}'``。
    """
    for line in reversed((attach_output or "").splitlines()):
        if "/Volumes/" not in line:
            continue
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].startswith("/Volumes/"):
            return parts[2].strip()
        idx = line.find("/Volumes/")
        if idx >= 0:
            return line[idx:].strip()
    return ""


def verify_macos_dmg_download(path: Path, expected_size: int = 0) -> None:
    """安装前校验 DMG：大小与可挂载性。

    Raises:
        RuntimeError: 文件不完整或无法挂载。
    """
    if not path.is_file():
        raise RuntimeError(f"更新包不存在: {path}")
    size = path.stat().st_size
    if expected_size > 0 and size < int(expected_size * 0.98):
        raise RuntimeError(
            f"更新包不完整（已下载 {size} 字节，期望约 {expected_size} 字节），请重新检查更新"
        )
    hide = subprocess_hide_console_kwargs()
    proc = subprocess.run(
        ["/usr/bin/hdiutil", "attach", str(path), "-nobrowse", "-readonly", "-noverify"],
        capture_output=True,
        text=True,
        **hide,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        detail = output.strip().splitlines()[-1] if output.strip() else f"退出码 {proc.returncode}"
        raise RuntimeError(f"更新包无法挂载: {detail}")
    mount = parse_hdiutil_attach_mount_point(output)
    if not mount or not Path(mount).is_dir():
        raise RuntimeError("无法解析 DMG 挂载点")
    try:
        apps = list(Path(mount).glob("*.app"))
        if not apps:
            raise RuntimeError("DMG 内未找到 .app")
    finally:
        subprocess.run(
            ["/usr/bin/hdiutil", "detach", mount, "-quiet"],
            check=False,
            **hide,
        )


def macos_install_target_app() -> Path:
    """更新安装目标：已在「应用程序」中则原地覆盖，否则安装到「应用程序」。"""
    name = "GitPullSwitchTool-Sausage.app" if is_sausage_build() else "GitPullSwitchTool.app"
    applications = Path("/Applications") / name
    current = _macos_running_app_bundle()
    try:
        current_resolved = current.resolve()
        if current_resolved.parent == Path("/Applications").resolve():
            return current_resolved
    except OSError:
        pass
    return applications


def _write_macos_apply_script(
    script_path: Path,
    pid: int,
    dmg_path: Path,
    target_app: Path,
    log_path: Path,
) -> None:
    """主进程退出后再 ditto 替换 .app，并打开「应用程序」中的新版本。"""
    content = f"""#!/bin/bash
set -euo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
LOG="{log_path}"
DMG="{dmg_path}"
TARGET="{target_app}"
PID={pid}
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') apply update pid=$PID ==="
echo "DMG=$DMG"
echo "TARGET=$TARGET"

while kill -0 "$PID" 2>/dev/null; do
  sleep 1
done
sleep 2

fail() {{
  msg="$1"
  echo "FAILED: $msg"
  /usr/bin/osascript -e "display alert \\"Git 拉线切线工具更新失败\\" message \\"${{msg}}\\\\n\\\\n详见：$LOG\\" as critical" 2>/dev/null || true
  exit 1
}}

MOUNT=""
cleanup() {{
  if [ -n "$MOUNT" ] && [ -d "$MOUNT" ]; then
    /usr/bin/hdiutil detach "$MOUNT" -quiet 2>/dev/null || true
  fi
}}
trap cleanup EXIT

ATTACH_OUT="$(/usr/bin/hdiutil attach "$DMG" -nobrowse 2>&1)" || fail "无法挂载更新 DMG：$ATTACH_OUT"
# hdiutil 以制表符分隔；卷名可能含空格，第三列为 /Volumes/...
MOUNT="$(echo "$ATTACH_OUT" | /usr/bin/grep '/Volumes/' | /usr/bin/tail -1 | /usr/bin/awk -F'\\t' '{{print $3}}')"
if [ -z "$MOUNT" ] || [ ! -d "$MOUNT" ]; then
  MOUNT="$(echo "$ATTACH_OUT" | /usr/bin/tail -1 | /usr/bin/awk -F'\\t' '{{print $3}}')"
fi
[ -n "$MOUNT" ] && [ -d "$MOUNT" ] || fail "无法解析 DMG 挂载点（hdiutil 输出已写入日志）"
echo "MOUNT=$MOUNT"

SRC_APP="$(/usr/bin/find "$MOUNT" -maxdepth 1 -name '*.app' | /usr/bin/head -1)"
[ -n "$SRC_APP" ] || fail "DMG 内未找到 .app"

TARGET_DIR="$(/usr/bin/dirname "$TARGET")"
/bin/mkdir -p "$TARGET_DIR" || fail "无法创建安装目录：$TARGET_DIR"
/usr/bin/ditto "$SRC_APP" "$TARGET" || fail "无法写入「应用程序」中的 .app（请确认已完全退出本程序）"

echo "Installed to $TARGET"
/usr/bin/open "$TARGET" || fail "无法启动新版本"
/usr/bin/open -R "$TARGET"
/usr/bin/osascript -e 'display notification "已安装到「应用程序」并正在启动" with title "Git 拉线切线工具"' 2>/dev/null || true
echo "Done"
"""
    script_path.write_text(content, encoding="utf-8")
    script_path.chmod(0o755)


def reveal_path_in_finder(path: Path) -> None:
    """在 Finder 中选中并显示文件或文件夹（macOS）。"""
    if sys.platform != "darwin":
        return
    resolved = path.resolve()
    if not resolved.exists():
        return
    hide = subprocess_hide_console_kwargs()
    subprocess.run(
        ["/usr/bin/open", "-R", str(resolved)],
        check=False,
        **hide,
    )


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
            bat = get_updates_dir() / "apply_update_setup.bat"
            _write_windows_setup_bat(
                bat,
                pid,
                package_path,
                windows_installed_exe_path(),
            )
            subprocess.Popen(
                ["cmd", "/c", str(bat)],
                cwd=str(get_updates_dir()),
                **hide,
            )
            return
        target = Path(sys.executable).resolve()
        bat = get_updates_dir() / "apply_update.bat"
        _write_windows_portable_bat(bat, pid, package_path, target)
        subprocess.Popen(["cmd", "/c", str(bat)], **hide)
        return

    if sys.platform == "darwin":
        target_app = macos_install_target_app()
        updates_dir = get_updates_dir()
        script = updates_dir / "apply_update.sh"
        log_path = updates_dir / "apply_update.log"
        _write_macos_apply_script(
            script,
            pid,
            package_path.resolve(),
            target_app,
            log_path,
        )
        subprocess.Popen(
            ["/bin/bash", str(script)],
            start_new_session=True,
            cwd=str(updates_dir),
        )
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
