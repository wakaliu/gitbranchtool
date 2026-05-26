"""编排更新检查、弹窗、下载与退出后安装。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
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
from .release_checker import UpdateOffer, check_for_update_safe, probe_release_asset_size
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
    macos_install_target_app,
    probe_release_asset_size_curl,
    read_curl_download_error,
    start_curl_download,
    terminate_curl_download,
    verify_macos_dmg_download,
    reveal_path_in_finder,
)

_STARTUP_CHECK_DELAY_MS = 2000
_INSTALL_NOTICE_MS = 6500
_DOWNLOAD_STALL_HINT_SEC = 20
_DOWNLOAD_STALL_ABORT_SEC = 90
_MAX_CURL_DOWNLOAD_RETRIES = 2


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
        self._download_bytes_done = 0
        self._download_bytes_total = 0
        self._download_last_size = 0
        self._download_last_growth_at = 0.0
        self._curl_proc: Optional[subprocess.Popen] = None
        self._curl_offer: Optional[UpdateOffer] = None
        self._download_dest: Optional[Path] = None
        self._curl_retry_count = 0
        self._download_progress_timer = QTimer(self)
        self._download_progress_timer.setInterval(250)
        self._download_progress_timer.timeout.connect(self._refresh_download_progress_ui)

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

        if sys.platform == "darwin":
            QTimer.singleShot(0, lambda: self._run_check_on_main_thread(auto))
            return

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

    def _run_check_on_main_thread(self, auto: bool) -> None:
        """macOS 在主线程检查更新，避免 QThreadPool 与 requests/SSL 交互崩溃。"""
        try:
            result = check_for_update_safe(
                self._current_version_str(),
                self._settings.language,
            )
            self._on_check_finished(result, auto)
        except Exception as exc:
            self._on_check_error(str(exc), auto)

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

    def _refresh_download_progress_ui(self) -> None:
        """由主线程定时器驱动进度刷新；macOS curl 下载在此轮询子进程。"""
        if self._curl_proc is not None:
            self._poll_curl_download()
            return
        self._apply_download_progress(self._download_bytes_done, self._download_bytes_total)

    def _poll_curl_download(self) -> None:
        """轮询 curl 子进程与本地文件大小（仅主线程）。"""
        proc = self._curl_proc
        dest = self._download_dest
        offer = self._curl_offer
        if proc is None or dest is None or offer is None:
            return
        now = time.monotonic()
        if dest.exists():
            try:
                size = dest.stat().st_size
                if size > self._download_last_size:
                    self._download_last_size = size
                    self._download_last_growth_at = now
                self._download_bytes_done = size
                if size > self._download_bytes_total:
                    self._download_bytes_total = size
            except OSError:
                pass
        curl_running = proc.poll() is None
        stalled_sec = now - self._download_last_growth_at
        stall_hint = curl_running and stalled_sec >= _DOWNLOAD_STALL_HINT_SEC
        stall_retry = curl_running and stalled_sec >= _DOWNLOAD_STALL_ABORT_SEC
        if stall_retry:
            if self._curl_retry_count < _MAX_CURL_DOWNLOAD_RETRIES:
                self._retry_curl_download()
                return
            terminate_curl_download(proc)
            self._curl_proc = None
            self._stop_download_progress_timer()
            self._cleanup_partial_download(dest)
            t = get_update_texts(self._settings.language)
            self._on_download_worker_error(t.msg_download_stalled)
            return
        self._apply_download_progress(
            self._download_bytes_done,
            self._download_bytes_total,
            curl_running=curl_running,
            stall_hint=stall_hint,
        )
        if curl_running:
            return
        self._curl_proc = None
        self._stop_download_progress_timer()
        if self._cancel_requested:
            self._cleanup_partial_download(dest)
            self._cleanup_progress_dialog()
            self._end_flow_unlock()
            return
        if proc.returncode != 0:
            self._cleanup_partial_download(dest)
            self._on_download_worker_error(read_curl_download_error(proc))
            return
        self._on_download_finished((offer, str(dest)))

    def _cleanup_partial_download(self, dest: Path) -> None:
        try:
            if dest.exists():
                dest.unlink()
        except OSError:
            pass

    def _retry_curl_download(self) -> None:
        """下载长时间无字节增长时终止 curl 并以 ``-C -`` 断点续传。"""
        offer = self._curl_offer
        dest = self._download_dest
        if offer is None or dest is None:
            return
        proc = self._curl_proc
        if proc is not None:
            terminate_curl_download(proc)
            self._curl_proc = None
        self._curl_retry_count += 1
        t = get_update_texts(self._settings.language)
        self._append_log(
            t.log_download_retry.format(
                attempt=self._curl_retry_count,
                max_attempts=_MAX_CURL_DOWNLOAD_RETRIES,
            )
        )
        try:
            if dest.exists():
                size = dest.stat().st_size
                self._download_bytes_done = size
                self._download_last_size = size
        except OSError:
            pass
        self._download_last_growth_at = time.monotonic()
        try:
            self._curl_proc, self._download_dest = start_curl_download(offer, resume=True)
        except OSError as exc:
            self._stop_download_progress_timer()
            self._on_download_worker_error(str(exc))
            return
        self._apply_download_progress(
            self._download_bytes_done,
            self._download_bytes_total,
            curl_running=True,
            stall_hint=False,
            stall_retry=True,
        )

    def _abort_curl_download(self) -> None:
        proc = self._curl_proc
        if proc is not None:
            terminate_curl_download(proc)
            self._curl_proc = None
        dest = self._download_dest
        if dest is not None:
            self._cleanup_partial_download(dest)

    def _stop_download_progress_timer(self) -> None:
        self._download_progress_timer.stop()

    def _apply_download_progress(
        self,
        done: int,
        total: int,
        *,
        curl_running: bool = False,
        stall_hint: bool = False,
        stall_retry: bool = False,
    ) -> None:
        """在主线程更新下载进度条。"""
        if self._progress is None or self._cancel_requested:
            return
        t = get_update_texts(self._settings.language)
        if total <= 0 and done <= 0:
            self._progress.set_download_indeterminate(t.progress_label)
            return
        display_total = max(total, done) if total > 0 else done
        total_mb = display_total / (1024 * 1024) if display_total > 0 else 0.0
        if display_total > 0:
            percent = int(done * 100 / display_total)
            if curl_running and percent >= 99:
                percent = 99
        else:
            percent = 0
        if done <= 0 and total > 0:
            detail = t.progress_label
        elif display_total > 0:
            detail = t.progress_downloading.format(
                done_mb=done / (1024 * 1024),
                total_mb=total_mb,
            )
        else:
            detail = t.progress_download_unknown_total.format(
                done_mb=done / (1024 * 1024),
            )
        if curl_running and total > 0 and done >= int(total * 0.92):
            detail = f"{detail}\n{t.progress_download_finishing}"
        if stall_retry:
            detail = f"{detail}\n{t.progress_download_stall_retry}"
        elif stall_hint:
            detail = f"{detail}\n{t.progress_download_slow}"
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

        self._download_bytes_done = 0
        if sys.platform == "darwin":
            probed_size = probe_release_asset_size_curl(offer.download_url)
        else:
            probed_size = probe_release_asset_size(offer.download_url)
        self._download_bytes_total = probed_size or int(offer.asset_size or 0)
        self._download_last_size = 0
        self._download_last_growth_at = time.monotonic()
        self._curl_proc = None
        self._curl_offer = None
        self._download_dest = None
        self._curl_retry_count = 0

        if sys.platform == "darwin":
            try:
                self._curl_offer = offer
                self._curl_proc, self._download_dest = start_curl_download(offer)
                self._download_progress_timer.start()
            except OSError as exc:
                self._cleanup_progress_dialog()
                self._end_flow_unlock()
                QMessageBox.warning(
                    self._parent,
                    t.msg_download_failed_title,
                    str(exc),
                )
            return

        self._download_progress_timer.start()

        def do_download() -> tuple[UpdateOffer, str]:
            def on_progress(done: int, total: int) -> None:
                self._download_bytes_done = done
                if total > 0:
                    self._download_bytes_total = total

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
        self._stop_download_progress_timer()
        self._abort_curl_download()
        if not self._cancel_requested:
            self._cancel_requested = True
            self._append_log(get_update_texts(self._settings.language).log_cancelled)
        self._progress = None
        self._end_flow_unlock()

    def _on_download_finished(self, result: tuple[UpdateOffer, str]) -> None:
        self._stop_download_progress_timer()
        self._curl_proc = None
        self._curl_offer = None
        self._download_dest = None
        if self._cancel_requested:
            self._cleanup_progress_dialog()
            self._end_flow_unlock()
            return
        offer, path_str = result
        t = get_update_texts(self._settings.language)
        self._append_log(t.log_download_done.format(path=path_str))
        if self._download_bytes_total > 0:
            self._download_bytes_done = self._download_bytes_total
        self._apply_download_progress(self._download_bytes_done, self._download_bytes_total)

        package_path = get_updates_dir() / offer.asset_name
        install_detail = t.install_background_detail
        if sys.platform == "darwin":
            target = macos_install_target_app()
            install_detail = t.install_background_detail_macos.format(
                path=target,
                dmg_path=package_path,
            )
            self._append_log(t.log_install_macos_target.format(path=target))
            self._append_log(t.log_download_saved.format(path=package_path))
        if self._progress:
            self._progress.set_install_phase(install_detail)
        self._append_log(t.log_install_background)

        try:
            if sys.platform == "darwin":
                expected = int(offer.asset_size or self._download_bytes_total or 0)
                verify_macos_dmg_download(package_path, expected_size=expected)
                reveal_path_in_finder(package_path)
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
        self._stop_download_progress_timer()
        self._abort_curl_download()
        self._curl_offer = None
        self._download_dest = None
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
        self._abort_curl_download()
        pause_bg = getattr(self._parent, "pause_background_tasks_for_update", None)
        if callable(pause_bg):
            pause_bg()
        self._cleanup_progress_dialog()
        app = QApplication.instance()
        if not app:
            return
        for widget in app.topLevelWidgets():
            widget.close()
        QApplication.processEvents()
        app.exit(0)
