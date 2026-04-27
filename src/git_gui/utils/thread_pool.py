"""线程池封装。

统一管理 QThreadPool，限制并发数，防止 CPU/内存过高。
"""
from PySide6.QtCore import QThreadPool, QRunnable, QObject, Signal
from typing import Callable, Any
import traceback

class WorkerSignals(QObject):
    """线程信号，用于安全地将结果/错误传回主线程。"""
    finished = Signal(object)   # 成功结果
    error = Signal(str)         # 错误信息
    progress = Signal(str)      # 实时进度/日志

class Worker(QRunnable):
    """可重用工作线程。

    封装了 try/except 和信号发射，减少重复代码。
    """
    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            tb = traceback.format_exc()
            self.signals.error.emit(f"{str(e)}\n{tb}")

class ThreadPoolManager:
    """全局线程池管理器。

    为什么限制 max_concurrent：防止同时打开过多 git 进程导致系统卡顿或文件锁冲突。
    默认值从配置读取。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pool = QThreadPool.globalInstance()
            # 将在 Settings 加载后由核心层设置
            cls._instance._pool.setMaxThreadCount(6)
        return cls._instance

    def set_max_threads(self, count: int) -> None:
        """动态调整并发数 (设置页面可修改)。"""
        if 1 <= count <= 16:
            self._pool.setMaxThreadCount(count)

    def start(self, worker: Worker) -> None:
        self._pool.start(worker)

    @property
    def active_thread_count(self) -> int:
        return self._pool.activeThreadCount()
