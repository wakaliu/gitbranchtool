"""应用更新下载/安装进度对话框（独立于 Git 操作 QProgressDialog）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QProgressBar,
)

from ..i18n.update_texts import get_update_texts


class UpdateProgressDialog(QDialog):
    """展示下载与安装两阶段进度；用户点 X 视为取消更新。"""

    def __init__(self, parent=None, language: str = "zh"):
        super().__init__(parent)
        self._language = language
        self._user_closed = False
        self.setModal(True)
        self.setMinimumWidth(420)
        self._phase_label = QLabel(self)
        self._phase_label.setProperty("role", "section-title")
        self._detail_label = QLabel(self)
        self._detail_label.setProperty("role", "secondary")
        self._detail_label.setWordWrap(True)
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._phase_label)
        layout.addWidget(self._bar)
        layout.addWidget(self._detail_label)
        self.apply_language(language)

    def apply_language(self, language: str) -> None:
        """刷新标题与阶段文案。"""
        self._language = language
        t = get_update_texts(language)
        self.setWindowTitle(t.progress_title)

    def set_download_progress(self, percent: int, detail: str) -> None:
        """更新下载阶段进度（0–100）。"""
        t = get_update_texts(self._language)
        self._phase_label.setText(t.phase_download)
        self._bar.setRange(0, 100)
        self._bar.setValue(max(0, min(100, percent)))
        self._detail_label.setText(detail)

    def set_download_indeterminate(self, detail: str) -> None:
        """连接服务器或尚未获知大小时显示忙碌进度条。"""
        t = get_update_texts(self._language)
        self._phase_label.setText(t.phase_download)
        self._bar.setRange(0, 0)
        self._detail_label.setText(detail)

    def set_install_phase(self, detail: str) -> None:
        """进入安装阶段（忙碌进度条，等待后台 Setup）。"""
        t = get_update_texts(self._language)
        self._phase_label.setText(t.phase_install)
        self._bar.setRange(0, 0)
        self._detail_label.setText(detail)

    def was_user_closed(self) -> bool:
        return self._user_closed

    def closeEvent(self, event) -> None:
        self._user_closed = True
        super().closeEvent(event)

    def reject(self) -> None:
        self._user_closed = True
        super().reject()
