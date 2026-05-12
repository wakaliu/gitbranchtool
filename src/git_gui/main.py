"""应用入口。

创建 QApplication，加载主窗口，设置高 DPI 支持。
"""
import sys
from pathlib import Path
import threading
import faulthandler
import os
import subprocess


def _fatal_logs_dir() -> Path:
    """与 runtime_paths 对齐的日志目录，仅依赖标准库，供 PySide6 未安装时仍能落盘。"""
    app = "GitPullSwitchTool"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app / "logs"
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(local) / app / "logs"
    return Path.home() / ".local" / "share" / app / "logs"


def _write_startup_fatal_log(title: str, detail: str) -> Path:
    """将致命启动错误写入固定路径，避免双击 .app 无终端时完全无据可查。"""
    log_dir = _fatal_logs_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "startup-fatal.log"
    path.write_text(f"{title}\n\n{detail}\n", encoding="utf-8")
    return path


def _hint_fix_pyside() -> str:
    if getattr(sys, "frozen", False):
        return "当前为打包版：请重新用完整依赖环境构建安装包，或向发布方索取可运行版本。"
    root = Path(__file__).resolve().parents[2]
    req = root / "requirements.txt"
    if req.is_file():
        return f"请在仓库根执行:\n  python3 -m pip install --force-reinstall -r {req}"
    return "请执行: python3 -m pip install --force-reinstall PySide6-Essentials PySide6"


def _notify_startup_fatal(log_path: Path, summary: str) -> None:
    """在无 Qt 时使用系统原生提示，便于非开发者发现失败原因。"""
    if sys.platform == "darwin":
        try:
            esc = summary.replace("\\", "\\\\").replace('"', '\\"')
            esc_path = str(log_path).replace("\\", "\\\\").replace('"', '\\"')
            # Popen：避免 run 阻塞至用户点掉对话框后才退出（脚本/自动化会挂死）。
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    f'display alert "GitPullSwitchTool 无法启动" '
                    f'message "{esc}\\n\\n详细日志:\\n{esc_path}" as critical',
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    elif os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, f"{summary}\n\n日志:\n{log_path}", "GitPullSwitchTool", 0x10)
        except Exception:
            pass


try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QCoreApplication, qInstallMessageHandler
    from PySide6.QtGui import QIcon
except ImportError as exc:
    detail = f"{type(exc).__name__}: {exc}\n\n{_hint_fix_pyside()}"
    log_path = _write_startup_fatal_log("无法导入 PySide6（图形界面依赖缺失）", detail)
    _notify_startup_fatal(log_path, "缺少 PySide6，无法启动图形界面。")
    sys.exit(1)

if __package__ in (None, ""):
    # 兼容直接脚本启动: python src/git_gui/main.py
    _project_root = Path(__file__).resolve().parents[2]
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))
    from src.git_gui.config.settings import Settings
    from src.git_gui.ui.main_window import MainWindow
    from src.git_gui.utils.logger import write_exception_log, write_error_log
    from src.git_gui.utils.runtime_paths import get_logs_dir, get_application_root_for_diagnostics, get_app_icon_png_path
else:
    from .config.settings import Settings
    from .ui.main_window import MainWindow
    from .utils.logger import write_exception_log, write_error_log
    from .utils.runtime_paths import get_logs_dir, get_application_root_for_diagnostics, get_app_icon_png_path

_LOG_DIR = get_logs_dir()
_PROJECT_ROOT = get_application_root_for_diagnostics()
# 进程存活期间必须保持打开：若在 with 块内 enable(f) 后关闭 f，faulthandler 会写到已关闭句柄，易随机闪退。
_FAULT_LOG_FP = None

def _reset_session_log_files(log_dir: Path) -> None:
    """每次进程启动时删除会话日志文件，便于单次运行对照排查闪退。

    设置环境变量 GITTOOL_KEEP_LOGS=1（或 true/yes）则保留历史，改为追加写入。
    """
    keep = os.environ.get("GITTOOL_KEEP_LOGS", "").strip().lower()
    if keep in ("1", "true", "yes", "on"):
        return
    for name in ("app-error.log", "fault.log"):
        path = log_dir / name
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

def _qt_message_handler(mode, context, message):
    try:
        write_error_log("Qt消息", f"{mode} | {message}")
    except Exception:
        pass

def _install_global_exception_hooks() -> None:
    """安装全局异常钩子，将未捕获异常写入本地日志。"""
    def handle_exception(exc_type, exc_value, exc_tb):
        write_exception_log("主线程未捕获异常", exc_type, exc_value, exc_tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def handle_thread_exception(args):
        write_exception_log("子线程未捕获异常", args.exc_type, args.exc_value, args.exc_traceback)
        if hasattr(threading, "__excepthook__"):
            threading.__excepthook__(args)

    sys.excepthook = handle_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception

def main() -> None:
    """程序入口函数。"""
    os.environ["GITTOOL_LOG_DIR"] = str(_LOG_DIR)
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _reset_session_log_files(_LOG_DIR)
    write_error_log(
        "应用启动",
        f"cwd={Path.cwd()}\napp_root={_PROJECT_ROOT}\nlog_dir={_LOG_DIR}",
    )
    _install_global_exception_hooks()
    global _FAULT_LOG_FP
    try:
        _FAULT_LOG_FP = open(_LOG_DIR / "fault.log", "a", encoding="utf-8")
        faulthandler.enable(_FAULT_LOG_FP, all_threads=True)
        faulthandler.dump_traceback_later(30, repeat=True, file=_FAULT_LOG_FP)
    except Exception as e:
        write_error_log("初始化故障日志失败", str(e))
        _FAULT_LOG_FP = None
    qInstallMessageHandler(_qt_message_handler)

    # 高 DPI 支持 (Windows/macOS 必需)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("GitPullSwitchTool")
        app.setOrganizationName("SausageDev")
        icon_path = get_app_icon_png_path()
        if icon_path is not None:
            app.setWindowIcon(QIcon(str(icon_path)))

        # 加载设置 (确保 config.yaml 存在)
        settings = Settings()

        window = MainWindow()
        window.show()

        exit_code = app.exec()
        faulthandler.cancel_dump_traceback_later()
        sys.exit(exit_code)
    except Exception as e:
        write_error_log("main() 异常退出", str(e))
        raise


if __name__ == "__main__":
    main()
