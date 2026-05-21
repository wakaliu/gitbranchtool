"""编排更新检查、弹窗、下载与退出后安装。"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ...config.constants import APP_VERSION
from ...config.settings import Settings
from ...ui.components.update_dialog import UpdateDialog, UpdateDialogResult
from ...ui.components.update_progress_dialog import UpdateProgressDialog
from ...ui.i18n.update_texts import UpdateTextBundle, get_update_texts
from ...utils.runtime_paths import is_pyinstaller_bundle
from ...utils.thread_pool import ThreadPoolManager, Worker
from .check_messages import UpdateCheckFailureText, format_update_check_failure
from .release_checker import UpdateOffer, check_for_update_safe
from .update_throttle import (
    evaluate_update_check_gate,
    rate_limit_backoff_reset_hint,
    record_auto_check_attempt,
    startup_check_cooldown_minutes,
    startup_cooldown_remaining_seconds,
)
from .update_installer import (
    UpdateDownloadCancelled,
    download_update,
    get_updates_dir,
    launch_apply_after_quit,
)

_STARTUP_CHECK_DELAY_MS = 2000
_INSTALL_NOTICE_MS = 2500


class UpdateController(QObject):
    """主窗口持有的更新流程控制器。"""

    def __init__(
        self,
        parent: QWidget,
        dispatch_to_main: Callable[[Callable], None],
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._parent = parent
        self._dispatch_to_main = dispatch_to_main
        self._log = log_fn
        self._settings = Settings()
        self._thread_pool = ThreadPoolManager()
        self._checking = False
        self._flow_active = False
        self._cancel_requested = False
        self._install_launched = False
        self._open_dialog: Optional[UpdateDialog] = None
        self._progress: Optional[UpdateProgressDialog] = None
        self._active_worker: Optional[Worker] = None
        self._ignore_progress_close = False

    def schedule_startup_check(self) -> None:
        """打包版且开启启动检查时，延迟触发自动检测。"""
        if not is_pyinstaller_bundle():
            return
        if not self._settings.get("update.check_on_startup", True):
            return
        QTimer.singleShot(_STARTUP_CHECK_DELAY_MS, lambda: self.run_check(auto=True))

    def on_language_changed(self) -> None:
        """设置页切换语言后刷新已打开的更新对话框。"""
        if self._open_dialog is not None:
            self._open_dialog.apply_language(self._settings.language)
        if self._progress is not None:
            self._progress.apply_language(self._settings.language)

    def is_flow_active(self) -> bool:
        return self._flow_active

    def cancel_flow(self) -> None:
        """主窗口关闭或用户取消时终止更新流程。"""
        self._cancel_requested = True
        if self._progress is not None:
            self._progress.close()
            self._progress = None
        self._end_flow_unlock()

    def _append_log(self, message: str) -> None:
        if self._log:
            self._log(message)

    def _set_flow_locked(self, locked: bool) -> None:
        self._flow_active = locked
        lock_fn = getattr(self._parent, "set_update_flow_locked", None)
        if callable(lock_fn):
            lock_fn(locked)

    def _begin_flow_lock(self) -> None:
        self._cancel_requested = False
        self._install_launched = False
        self._set_flow_locked(True)

    def _end_flow_unlock(self) -> None:
        self._flow_active = False
        self._cancel_requested = False
        self._install_launched = False
        self._active_worker = None
        self._set_flow_locked(False)

    def run_check(self, auto: bool) -> None:
        """执行一次更新检查（后台线程）。"""
        if self._checking or self._flow_active:
            return
        if not is_pyinstaller_bundle():
            return

        t = get_update_texts(self._settings.language)
        gate = evaluate_update_check_gate(self._settings, auto=auto)
        if not gate.allowed:
            if gate.failure is not None:
                when = rate_limit_backoff_reset_hint(
                    self._settings, self._settings.language
                )
                when_text = f"约 {when} 后可重试" if when else "请稍后再试"
                self._append_log(
                    t.log_skip_rate_limit_backoff.format(when=when_text)
                )
                if not auto:
                    QMessageBox.warning(
                        self._parent,
                        t.msg_check_failed_title,
                        gate.failure.dialog_message,
                    )
            elif gate.silent:
                remain_sec = startup_cooldown_remaining_seconds(self._settings)
                if remain_sec > 0:
                    self._append_log(
                        t.log_skip_startup_cooldown.format(
                            cooldown=startup_check_cooldown_minutes(self._settings),
                            remain=self._format_cooldown_remain(remain_sec),
                        )
                    )
            return

        if auto:
            record_auto_check_attempt(self._settings)
        self._checking = True
        self._append_log(t.log_check_start)
        parent = self._parent
        if hasattr(parent, "statusBar"):
            parent.statusBar().showMessage(t.status_checking)
        if hasattr(parent, "_action_check_update"):
            parent._action_check_update.setEnabled(False)

        worker = Worker(
            check_for_update_safe,
            self._current_version_str(),
            self._settings.language,
        )
        worker.signals.finished.connect(
            lambda result: self._dispatch_to_main(
                lambda: self._on_check_finished(result, auto)
            )
        )
        worker.signals.error.connect(
            lambda err: self._dispatch_to_main(
                lambda: self._on_check_error(err, auto)
            )
        )
        self._thread_pool.start(worker)

    def _current_version_str(self) -> str:
        return str(self._settings.get("app.version", APP_VERSION) or APP_VERSION).strip()

    @staticmethod
    def _format_cooldown_remain(remain_sec: int) -> str:
        """将剩余秒数格式化为日志/提示用短文案。"""
        if remain_sec >= 120:
            return f"{(remain_sec + 59) // 60} 分钟"
        if remain_sec >= 60:
            return "1 分钟"
        return f"{remain_sec} 秒"

    def _on_check_finished(
        self,
        result: tuple[Optional[UpdateOffer], Optional[UpdateCheckFailureText]],
        auto: bool,
    ) -> None:
        self._checking = False
        self._restore_status_after_check()
        offer, failure = result
        t = get_update_texts(self._settings.language)
        if failure is not None:
            self._append_log(failure.log_line)
            if not auto:
                QMessageBox.warning(
                    self._parent,
                    t.msg_check_failed_title,
                    failure.dialog_message,
                )
            return
        if offer is None:
            if not auto:
                QMessageBox.information(
                    self._parent,
                    t.msg_latest_title,
                    t.msg_latest_body,
                )
            return
        if auto:
            dismissed = str(self._settings.get("update.auto_dismissed_version", "") or "").strip()
            if dismissed == offer.version:
                return
        self._show_offer_dialog(offer, auto)

    def _on_check_error(self, err: str, auto: bool) -> None:
        self._checking = False
        self._restore_status_after_check()
        failure = format_update_check_failure(
            self._settings.language, "unknown", detail=err
        )
        self._append_log(failure.log_line)
        if not auto:
            t = get_update_texts(self._settings.language)
            QMessageBox.warning(
                self._parent,
                t.msg_check_failed_title,
                failure.dialog_message,
            )

    def _restore_status_after_check(self) -> None:
        if self._flow_active:
            return
        parent = self._parent
        if hasattr(parent, "_action_check_update"):
            parent._action_check_update.setEnabled(True)
        if hasattr(parent, "_update_workspace_header"):
            parent._update_workspace_header()

    def _show_offer_dialog(self, offer: UpdateOffer, auto: bool) -> None:
        dialog = UpdateDialog(
            offer,
            self._current_version_str(),
            auto_mode=auto,
            parent=self._parent,
        )
        self._open_dialog = dialog
        dialog.exec()
        self._open_dialog = None
        result = dialog.user_result
        if result == UpdateDialogResult.DISMISS:
            self._settings.set("update.auto_dismissed_version", offer.version)
        elif result == UpdateDialogResult.UPDATE_NOW:
            self._start_download_and_install(offer)

    def _apply_download_progress(self, done: int, total: int) -> None:
        """在主线程更新下载进度条（避免 Worker progress 信号类型不匹配导致闪退）。"""
        if self._progress is None or self._cancel_requested:
            return
        t = get_update_texts(self._settings.language)
        if total <= 0 and done <= 0:
            self._progress.set_download_indeterminate(t.progress_label)
            return
        total_mb = total / (1024 * 1024) if total > 0 else 0.0
        percent = int(done * 100 / total) if total > 0 else 0
        if done <= 0 and total > 0:
            detail = t.progress_label
        else:
            detail = t.progress_downloading.format(
                done_mb=done / (1024 * 1024),
                total_mb=total_mb,
            )
        pct_text = t.progress_download_percent.format(percent=percent)
        self._progress.set_download_progress(percent, f"{pct_text}\n{detail}")

    def _start_download_and_install(self, offer: UpdateOffer) -> None:
        if self._flow_active:
            return
        self._begin_flow_lock()
        lang = self._settings.language
        t = get_update_texts(lang)
        self._append_log(t.log_download_start.format(name=offer.asset_name))

        self._progress = UpdateProgressDialog(self._parent, language=lang)
        self._progress.set_download_progress(0, t.progress_label)
        self._progress.finished.connect(self._on_progress_dialog_finished)
        self._progress.show()

        def do_download() -> tuple[UpdateOffer, str]:
            def on_progress(done: int, total: int) -> None:
                self._dispatch_to_main(
                    lambda d=done, tot=total: self._apply_download_progress(d, tot)
                )

            path = download_update(
                offer,
                on_progress=on_progress,
                should_cancel=lambda: self._cancel_requested,
            )
            return offer, str(path)

        worker = Worker(do_download)
        self._active_worker = worker
        worker.signals.finished.connect(
            lambda result: self._dispatch_to_main(
                lambda: self._on_download_finished(result)
            )
        )
        worker.signals.error.connect(
            lambda err: self._dispatch_to_main(
                lambda: self._on_download_worker_error(err)
            )
        )
        self._thread_pool.start(worker)

    def _on_progress_dialog_finished(self, _result: int) -> None:
        """用户关闭进度窗：取消下载/安装并恢复主界面。"""
        if self._ignore_progress_close or self._install_launched:
            return
        if not self._cancel_requested:
            self._cancel_requested = True
            self._append_log(get_update_texts(self._settings.language).log_cancelled)
        self._progress = None
        self._end_flow_unlock()

    def _on_download_finished(self, result: tuple[UpdateOffer, str]) -> None:
        if self._cancel_requested:
            self._cleanup_progress_dialog()
            self._end_flow_unlock()
            return
        offer, path_str = result
        t = get_update_texts(self._settings.language)
        self._append_log(t.log_download_done.format(path=path_str))

        if self._progress:
            self._progress.set_install_phase(t.install_background_detail)
        self._append_log(t.log_install_background)

        package_path = get_updates_dir() / offer.asset_name
        try:
            launch_apply_after_quit(package_path)
            self._install_launched = True
            self._append_log(t.log_install_quit)
            self._schedule_quit_after_install_notice(t)
        except Exception as exc:
            self._cleanup_progress_dialog()
            self._end_flow_unlock()
            QMessageBox.warning(
                self._parent,
                t.msg_install_failed_title,
                str(exc),
            )

    def _on_download_worker_error(self, err: str) -> None:
        self._cleanup_progress_dialog()
        t = get_update_texts(self._settings.language)
        if "UpdateDownloadCancelled" in err or "用户已取消" in err or "cancelled" in err.lower():
            self._append_log(t.log_cancelled)
            self._end_flow_unlock()
            return
        summary = err.splitlines()[0] if err else t.msg_download_failed_title
        self._append_log(f"{t.msg_download_failed_title}: {summary}")
        self._end_flow_unlock()
        QMessageBox.warning(
            self._parent,
            t.msg_download_failed_title,
            f"{summary}\n\n详见运行日志或 logs/app-error.log。",
        )

    def _cleanup_progress_dialog(self) -> None:
        if self._progress is not None:
            self._ignore_progress_close = True
            self._progress.blockSignals(True)
            self._progress.close()
            self._progress = None

    def _schedule_quit_after_install_notice(self, t: UpdateTextBundle) -> None:
        """在进度窗显示后台安装说明，定时关闭并退出（避免叠加模态 QMessageBox 导致无法 quit）。"""
        if self._progress is not None:
            self._ignore_progress_close = True
            self._progress.set_install_phase(t.msg_install_background)
            self._progress.raise_()
            self._progress.activateWindow()
        QApplication.processEvents()
        QTimer.singleShot(_INSTALL_NOTICE_MS, lambda: self._quit_for_install())

    def _quit_for_install(self) -> None:
        """关闭所有顶层窗口并结束事件循环，便于后台 bat 静默安装后拉起新版本。"""
        self._cleanup_progress_dialog()
        app = QApplication.instance()
        if not app:
            return
        for widget in app.topLevelWidgets():
            widget.close()
        QApplication.processEvents()
        app.exit(0)
