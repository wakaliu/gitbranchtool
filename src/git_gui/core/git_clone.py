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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..utils.subprocess_helpers import subprocess_git_command_kwargs, subprocess_hide_console_kwargs


@dataclass
class CloneOutputThrottle:
    """限制 git clone 输出映射到 UI 的频率，避免长时间 clone 时 Qt 事件队列膨胀导致闪退。

    clone 对话框与瘦身流程共用：在后台线程侧丢弃冗余 dispatch，而非在主线程排队后再忽略。
    """

    min_progress_interval: float = 0.5
    min_log_interval: float = 5.0
    heartbeat_log_interval: float = 30.0
    log_percent_bucket: int = 5
    last_log_key: str = ""
    last_log_at: float = 0.0
    last_progress_at: float = 0.0
    last_progress_key: str = ""
    last_git_line_at: float = field(default_factory=time.time)

    @staticmethod
    def is_noise_line(line: str) -> bool:
        """过滤 gc / commit-graph 等高频噪声，checkout 阶段每文件都可能触发。"""
        lower = line.lower()
        noise_fragments = (
            "auto packing the repository",
            "see \"git help gc\"",
            "collecting referenced commits",
            "loading known commits in commit graph",
            "expanding reachable commits in commit graph",
            "clearing commit marks in commit graph",
            "writing out commit graph",
        )
        return any(fragment in lower for fragment in noise_fragments)

    @staticmethod
    def _detect_phase(line_lower: str) -> str:
        for phase in (
            "enumerating objects",
            "counting objects",
            "compressing objects",
            "receiving objects",
            "resolving deltas",
            "checking connectivity",
            "updating files",
            "checking out files",
        ):
            if phase in line_lower:
                return phase
        return ""

    @classmethod
    def log_dedup_key(cls, line: str, *, percent_bucket: int) -> str:
        """按阶段 + 百分比分桶去重；Counting 1%/2%/3% 不再逐条刷日志。"""
        if cls.is_noise_line(line):
            return "__noise__"

        line_lower = line.lower()
        phase = cls._detect_phase(line_lower)
        frac = re.search(r"\((\d+)/(\d+)\)", line)
        pct = re.search(r"(\d+)%", line)

        if frac:
            current, total = int(frac.group(1)), int(frac.group(2))
            if total > 0:
                bucket = min(100, (current * 100) // total // percent_bucket * percent_bucket)
                return f"{phase}|{bucket}|{total}"

        if pct and phase:
            bucket = min(100, int(pct.group(1)) // percent_bucket * percent_bucket)
            return f"{phase}|pct{bucket}"

        stripped = line.strip()
        if len(stripped) > 96:
            return stripped[:96]
        return stripped

    def on_git_line(self, line: str) -> tuple[bool, bool]:
        """返回 (是否写日志, 是否更新进度条)。"""
        lower = line.lower()
        if "fatal:" in lower or "error:" in lower or "broken pipe" in lower:
            return True, True
        if self.is_noise_line(line):
            return False, False

        now = time.time()
        self.last_git_line_at = now
        log_key = self.log_dedup_key(line, percent_bucket=self.log_percent_bucket)
        if log_key == "__noise__":
            return False, False

        progress_key = log_key
        frac = re.search(r"\((\d+)/(\d+)\)", line)
        if frac:
            current, total = int(frac.group(1)), int(frac.group(2))
            if total > 0:
                progress_key = f"{self._detect_phase(lower)}|{current * 1000 // total}|{total}"

        log_key_changed = log_key != self.last_log_key
        progress_key_changed = progress_key != self.last_progress_key

        should_log = log_key_changed or (now - self.last_log_at) >= self.min_log_interval
        if should_log:
            self.last_log_key = log_key
            self.last_log_at = now

        should_progress = progress_key_changed or (now - self.last_progress_at) >= self.min_progress_interval
        if should_progress:
            self.last_progress_key = progress_key
            self.last_progress_at = now

        return should_log, should_progress

    def on_heartbeat(self) -> tuple[bool, bool]:
        """clone 心跳：进度按间隔刷新，日志仅在长时间无 git 输出时追加。"""
        now = time.time()
        should_progress = (now - self.last_progress_at) >= self.min_progress_interval
        if should_progress:
            self.last_progress_at = now

        should_log = (
            (now - self.last_log_at) >= self.heartbeat_log_interval
            and (now - self.last_git_line_at) >= 10.0
        )
        if should_log:
            self.last_log_at = now

        return should_log, should_progress


def clone_runtime_config_args() -> list[str]:
    """clone 期间注入的 git -c 配置，避免 checkout 时反复 auto gc 拖垮大仓。"""
    pairs = (
        ("gc.auto", "0"),
        ("maintenance.auto", "false"),
        ("core.preloadIndex", "false"),
    )
    args: list[str] = []
    for key, value in pairs:
        args.extend(["-c", f"{key}={value}"])
    return args


def build_script_clone_command(url: str, target: Path) -> list[str]:
    """构建与 sausage-biu 脚本一致的全量 clone（无 filter/depth/单分支参数）。"""
    return ["git", *clone_runtime_config_args(), "clone", "--progress", url, str(target)]


def build_repo_git_command(repo_path: Path, *git_args: str) -> list[str]:
    """在指定仓库目录执行 git 子命令。"""
    return ["git", *clone_runtime_config_args(), "-C", str(repo_path), *git_args]


def build_clone_command(url: str, target: Path, branch: str, shallow: bool) -> list[str]:
    """构建 git clone 命令。

    Args:
        url: 远程仓库地址。
        target: 本地目标路径。
        branch: 分支名；浅克隆时在 clone 阶段指定；全量 clone 由 ``run_script_style_clone_workflow`` 后续 checkout。
        shallow: True 时使用 ``--depth 1``；False 时仅全量 clone（需配合 fetch/checkout）。

    Returns:
        可直接传给 subprocess 的命令参数列表。
    """
    if shallow:
        cmd = ["git", *clone_runtime_config_args(), "clone", "--progress", url, str(target)]
        cmd.extend(["--depth", "1"])
        if branch:
            cmd.extend(["--branch", branch, "--single-branch"])
        return cmd
    return build_script_clone_command(url, target)


def run_script_style_clone_workflow(
    url: str,
    target: Path,
    branch: str,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    line_callback: Optional[Callable[[str], None]] = None,
    heartbeat_callback: Optional[Callable[[int], None]] = None,
    step_callback: Optional[Callable[[str], None]] = None,
    active_processes: Optional[list[subprocess.Popen]] = None,
) -> tuple[bool, str]:
    """全量 clone + fetch -f + checkout -B，与 sausage-biu 脚本 cloneAll 对齐。

    Args:
        url: 远程地址。
        target: 本地路径。
        branch: 目标分支；空则跳过 checkout 同步。
        cancel_check: 取消检查。
        line_callback: git 输出行回调。
        heartbeat_callback: 心跳回调（秒）。
        step_callback: 阶段切换回调（如「开始 fetch」）。
        active_processes: 可选进程跟踪列表。

    Returns:
        (是否成功, 失败摘要)。
    """
    workflow_start = time.time()

    def heartbeat() -> None:
        if heartbeat_callback:
            heartbeat_callback(int(time.time() - workflow_start))

    clone_cmd = build_script_clone_command(url, target)
    if step_callback:
        step_callback(f"clone：{' '.join(clone_cmd)}")
    ok, output = run_clone_process(
        clone_cmd,
        cancel_check=cancel_check,
        line_callback=line_callback,
        heartbeat_callback=lambda _elapsed: heartbeat(),
        active_processes=active_processes,
    )
    if not ok:
        return ok, output

    if cancel_check and cancel_check():
        return False, "cancelled"

    fetch_cmd = build_repo_git_command(target, "fetch", "--progress", "-f")
    if step_callback:
        step_callback(f"fetch：{' '.join(fetch_cmd)}")
    ok, output = run_clone_process(
        fetch_cmd,
        cancel_check=cancel_check,
        line_callback=line_callback,
        heartbeat_callback=lambda _elapsed: heartbeat(),
        active_processes=active_processes,
    )
    if not ok:
        return ok, output

    if cancel_check and cancel_check():
        return False, "cancelled"

    branch = (branch or "").strip()
    if not branch:
        return True, ""

    checkout_cmd = build_repo_git_command(
        target, "checkout", "-B", branch, f"origin/{branch}", "-f",
    )
    if step_callback:
        step_callback(f"checkout：{' '.join(checkout_cmd)}")
    ok, output = run_clone_process(
        checkout_cmd,
        cancel_check=cancel_check,
        line_callback=line_callback,
        heartbeat_callback=lambda _elapsed: heartbeat(),
        active_processes=active_processes,
    )
    return ok, output


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
