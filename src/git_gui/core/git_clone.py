"""Git clone 公共逻辑。

供克隆工程对话框与仓库瘦身复用，避免 UI 层重复实现 clone 命令与目录清理。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..utils.subprocess_helpers import subprocess_git_command_kwargs, subprocess_hide_console_kwargs


def build_clone_command(url: str, target: Path, branch: str, shallow: bool) -> list[str]:
    """构建 git clone 命令，仅拉取指定分支。

    Args:
        url: 远程仓库地址。
        target: 本地目标路径。
        branch: 分支名；空则使用远端默认分支。
        shallow: True 时使用 ``--depth 1``；False 时使用 ``--filter=blob:none``。

    Returns:
        可直接传给 subprocess 的命令参数列表。
    """
    cmd = ["git", "clone", "--progress", "--verbose", url, str(target)]
    if shallow:
        cmd.extend(["--depth", "1"])
    else:
        cmd.extend(["--filter=blob:none"])
    if branch:
        cmd.extend(["--branch", branch, "--single-branch"])
    return cmd


def remove_existing_path(target: Path) -> None:
    """删除已存在路径，为 re-clone 清场。

    Windows 上只读文件可能导致 rmtree 失败，通过 chmod 重试提高成功率。

    Args:
        target: 待删除的文件或目录。

    Raises:
        OSError: 删除失败且重试仍无法完成。
    """
    if target.is_file():
        target.unlink(missing_ok=True)
        return

    def on_rm_error(func, path, _exc_info):
        try:
            os.chmod(path, 0o777)
            func(path)
        except Exception as rm_err:
            raise rm_err

    shutil.rmtree(target, onerror=on_rm_error)


def terminate_clone_process(process: subprocess.Popen) -> None:
    """尽量完整终止 git clone 及其子进程。

    Args:
        process: 正在运行的 clone 子进程。
    """
    try:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                text=True,
                check=False,
                **subprocess_hide_console_kwargs(),
            )
        else:
            process.terminate()
            process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def run_clone_process(
    cmd: list[str],
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    line_callback: Optional[Callable[[str], None]] = None,
    heartbeat_callback: Optional[Callable[[int], None]] = None,
    active_processes: Optional[list[subprocess.Popen]] = None,
) -> tuple[bool, str]:
    """流式执行 git clone，定期心跳避免长时间无反馈。

    Args:
        cmd: clone 命令参数列表。
        cancel_check: 返回 True 时终止 clone。
        line_callback: 每行输出回调。
        heartbeat_callback: 心跳回调，参数为已耗时秒数。
        active_processes: 可选列表，用于外部跟踪并批量终止进程。

    Returns:
        (是否成功, 失败时的错误摘要)。
    """
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=0,
        **subprocess_git_command_kwargs(),
    )
    if active_processes is not None:
        active_processes.append(process)

    output_lines: list[str] = []
    start_time = time.time()
    last_heartbeat = 0.0
    stop_reader = threading.Event()

    def _emit_output_line(text: str) -> None:
        output_lines.append(text)
        if len(output_lines) > 30:
            output_lines[:] = output_lines[-30:]
        if line_callback:
            line_callback(text)

    def read_output_stream() -> None:
        if process.stdout is None:
            return
        pending = ""
        try:
            while not stop_reader.is_set():
                chunk = process.stdout.read(256)
                if not chunk:
                    break
                pending += chunk.replace("\r", "\n")
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    text = line.strip()
                    if text:
                        _emit_output_line(text)
            if pending.strip():
                _emit_output_line(pending.strip())
        except Exception:
            pass

    reader_thread = threading.Thread(target=read_output_stream, daemon=True)
    reader_thread.start()
    try:
        while process.poll() is None:
            if cancel_check and cancel_check():
                terminate_clone_process(process)
                stop_reader.set()
                reader_thread.join(timeout=1)
                return False, "cancelled"
            now = time.time()
            if heartbeat_callback and now - last_heartbeat >= 2:
                elapsed = int(now - start_time)
                heartbeat_callback(elapsed)
                last_heartbeat = now
            time.sleep(0.2)
        stop_reader.set()
        reader_thread.join(timeout=1)
        rc = process.wait(timeout=5)
        if rc == 0:
            return True, ""
        return False, (output_lines[-1] if output_lines else f"exit code {rc}")
    except Exception as e:
        terminate_clone_process(process)
        stop_reader.set()
        reader_thread.join(timeout=1)
        return False, str(e)
    finally:
        if active_processes is not None and process in active_processes:
            active_processes.remove(process)


def parse_clone_progress_percent(line: str) -> Optional[int]:
    """将 git clone 多阶段输出映射为 0–100 的整体进度。

    Git clone 会依次经历 Counting、Compressing、Receiving 等阶段，每阶段
    内部百分比会归零；若直接取行内首个 ``X%``，会在 Counting 100% 后误显
    100%。此处按阶段权重与 ``(current/total)`` 比值折算整体进度。

    Args:
        line: git clone 单行输出。

    Returns:
        0–100 的整数；无法解析时返回 None。
    """
    line_lower = line.lower()
    fraction = 0.0
    frac_match = re.search(r"\((\d+)/(\d+)\)", line)
    if frac_match:
        total = int(frac_match.group(2))
        if total > 0:
            fraction = min(1.0, int(frac_match.group(1)) / total)

    pct_match = re.search(r"(\d+)%", line)
    phase_fraction = fraction if frac_match else (
        int(pct_match.group(1)) / 100.0 if pct_match else 0.0
    )

    phase_weights: tuple[tuple[str, int, int], ...] = (
        ("enumerating objects", 0, 2),
        ("counting objects", 2, 6),
        ("compressing objects", 8, 17),
        ("receiving objects", 25, 60),
        ("resolving deltas", 85, 10),
        ("checking connectivity", 95, 1),
        ("updating files", 96, 4),
        ("checking out files", 96, 4),
    )
    for phase_key, start, span in phase_weights:
        if phase_key in line_lower:
            return max(0, min(100, start + int(phase_fraction * span)))

    if pct_match:
        try:
            return max(0, min(100, int(pct_match.group(1))))
        except ValueError:
            return None
    return None
