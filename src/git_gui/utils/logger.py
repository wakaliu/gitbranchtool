"""运行日志管理器。

仅负责日志的追加、滚动清理和耗时记录。UI 层通过信号驱动更新。
"""
from datetime import datetime
import time
from typing import Callable, Optional
from pathlib import Path
import traceback
import os

def _get_log_dir() -> Path:
    custom_dir = os.environ.get("GITTOOL_LOG_DIR", "").strip()
    if custom_dir:
        return Path(custom_dir)
    return Path("logs")

def write_error_log(title: str, details: str) -> None:
    """写入本地错误日志，便于排查闪退与异常。"""
    try:
        log_dir = _get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app-error.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"{datetime.now().isoformat()} | {title}\n")
            f.write(details.rstrip() + "\n")
    except Exception:
        # 日志写入失败时不再抛出，避免影响主流程
        pass

def write_exception_log(title: str, exc_type, exc_value, exc_tb) -> None:
    """写入异常堆栈到本地日志。"""
    details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    write_error_log(title, details)

class OperationLogger:
    """操作日志记录器。

    为什么独立成类：便于在多线程环境中安全追加日志，同时控制内存 (限制行数)。
    """
    def __init__(self, max_lines: int = 500, on_log_updated: Optional[Callable[[str], None]] = None):
        self.max_lines = max_lines
        self.on_log_updated = on_log_updated
        self._logs: list[str] = []
        self._start_time: Optional[float] = None

    def start_operation(self, operation_name: str) -> None:
        """开始一次操作计时。"""
        self._start_time = time.time()
        self.append(f"[{datetime.now().strftime('%H:%M:%S')}] 开始 {operation_name}...")

    def end_operation(self, success: bool = True, message: str = "") -> float:
        """结束操作，返回耗时 (秒)。"""
        if not self._start_time:
            return 0.0
        elapsed = time.time() - self._start_time
        status = "成功" if success else "失败"
        self.append(f"[{datetime.now().strftime('%H:%M:%S')}] {status}，耗时: {elapsed:.2f} 秒 {message}")
        self._start_time = None
        return elapsed

    def append(self, message: str) -> None:
        """追加日志并触发 UI 更新。

        只传递增量日志行 (而非全量join)，避免并行操作时重复发送大字符串导致UI卡顿或崩溃。
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        self._logs.append(log_line)

        # 滚动清理，保持内存占用低
        if len(self._logs) > self.max_lines:
            self._logs = self._logs[-self.max_lines:]

        if self.on_log_updated:
            self.on_log_updated(log_line)

    def clear(self) -> None:
        """清空日志 (用户手动或新操作前)。"""
        self._logs.clear()
        self._start_time = None
        if self.on_log_updated:
            self.on_log_updated("日志已清空。")

    def get_logs(self) -> str:
        return "\n".join(self._logs)
