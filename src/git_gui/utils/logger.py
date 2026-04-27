"""运行日志管理器。

仅负责日志的追加、滚动清理和耗时记录。UI 层通过信号驱动更新。
"""
from datetime import datetime
import time
from typing import Callable, Optional

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
        """追加日志并触发 UI 更新。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        self._logs.append(log_line)

        # 滚动清理，保持内存占用低
        if len(self._logs) > self.max_lines:
            self._logs = self._logs[-self.max_lines:]

        if self.on_log_updated:
            self.on_log_updated("\n".join(self._logs))

    def clear(self) -> None:
        """清空日志 (用户手动或新操作前)。"""
        self._logs.clear()
        self._start_time = None
        if self.on_log_updated:
            self.on_log_updated("日志已清空。")

    def get_logs(self) -> str:
        return "\n".join(self._logs)
