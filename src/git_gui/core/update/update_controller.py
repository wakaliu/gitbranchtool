"""编排更新检查、弹窗、下载与退出后安装。"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ...config.constants import APP_VERSION
from ...config.settings import Settings
from ...ui.components.update_dialog import UpdateDialog, UpdateDialogResult
from ...ui.i18n.update_texts import get_update_texts
from ...ui.widgets.progress_dialog import OperationProgressDialog
from ...utils.runtime_paths import is_pyinstaller_bundle
from ...utils.thread_pool import ThreadPoolManager, Worker
from .release_checker import UpdateOffer, check_for_update_safe
from .update_installer import download_update, launch_apply_after_quit

_STARTUP_CHECK_DELAY_MS = 2000


class UpdateController(QObject):
    """主窗口持有的更新流程控制器。"""

    def __init__(self, parent: QWidget, dispatch_to_main: Callable[[Callable], None]) -> None:
        super().__init__(parent)
        self._parent = parent
        self._dispatch_to_main = dispatch_to_main
        self._settings = Settings()
        self._thread_pool = ThreadPoolManager()
        self._checking = False
        self._open_dialog: Optional[UpdateDialog] = None
        self._progress: Optional[OperationProgressDialog] = None

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

    def run_check(self, auto: bool) -> None:
        """执行一次更新检查（后台线程）。"""
        if self._checking:
            return
        if not is_pyinstaller_bundle():
            return
        self._checking = True
        t = get_update_texts(self._settings.language)
        parent = self._parent
        if hasattr(parent, "statusBar"):
            parent.statusBar().showMessage(t.status_checking)
        if hasattr(parent, "_action_check_update"):
            parent._action_check_update.setEnabled(False)

        worker = Worker(check_for_update_safe, self._current_version_str())
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

    def _on_check_finished(
        self,
        result: tuple[Optional[UpdateOffer], Optional[str]],
        auto: bool,
    ) -> None:
        self._checking = False
        self._restore_status_after_check()
        offer, err = result
        t = get_update_texts(self._settings.language)
        if err:
            if not auto:
                QMessageBox.warning(self._parent, t.msg_check_failed_title, err)
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
        if not auto:
            t = get_update_texts(self._settings.language)
            QMessageBox.warning(self._parent, t.msg_check_failed_title, err)

    def _restore_status_after_check(self) -> None:
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

    def _start_download_and_install(self, offer: UpdateOffer) -> None:
        t = get_update_texts(self._settings.language)
        self._progress = OperationProgressDialog(self._parent, title=t.progress_title)
        self._progress.setLabelText(t.progress_label)
        self._progress.setCancelButton(None)
        self._progress.setRange(0, 0)
        self._progress.show()

        progress_emit_holder: dict = {}

        def do_download() -> UpdateOffer:
            def on_progress(done: int, total: int) -> None:
                total_mb = total / (1024 * 1024) if total > 0 else 0.0
                msg = t.progress_downloading.format(
                    done_mb=done / (1024 * 1024),
                    total_mb=total_mb,
                )
                emit = progress_emit_holder.get("emit")
                if emit:
                    emit(msg)

            download_update(offer, on_progress=on_progress)
            return offer

        worker = Worker(do_download)
        progress_emit_holder["emit"] = worker.signals.progress.emit
        worker.signals.progress.connect(
            lambda msg: self._dispatch_to_main(
                lambda: self._on_download_progress(msg)
            )
        )
        worker.signals.finished.connect(
            lambda _: self._dispatch_to_main(
                lambda: self._on_download_done(offer)
            )
        )
        worker.signals.error.connect(
            lambda err: self._dispatch_to_main(
                lambda: self._on_download_error(err)
            )
        )
        self._thread_pool.start(worker)

    def _on_download_progress(self, message: str) -> None:
        if self._progress:
            self._progress.update_status(message)

    def _on_download_done(self, offer: UpdateOffer) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        t = get_update_texts(self._settings.language)
        from .update_installer import get_updates_dir

        package_path = get_updates_dir() / offer.asset_name
        try:
            launch_apply_after_quit(package_path)
            QMessageBox.information(
                self._parent,
                t.dialog_title,
                t.msg_install_launch_body,
            )
            QApplication.instance().quit()
        except Exception as exc:
            QMessageBox.warning(
                self._parent,
                t.msg_install_failed_title,
                str(exc),
            )

    def _on_download_error(self, err: str) -> None:
        if self._progress:
            self._progress.close()
            self._progress = None
        t = get_update_texts(self._settings.language)
        QMessageBox.warning(self._parent, t.msg_download_failed_title, err)
