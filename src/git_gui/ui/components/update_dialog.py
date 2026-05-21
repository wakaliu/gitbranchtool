"""发现新版本时的更新对话框。"""
from __future__ import annotations

from enum import Enum, auto

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QSizePolicy,
)

from ...config.constants import APP_VERSION
from ...config.settings import Settings
from ...core.update.release_checker import UpdateOffer
from ..i18n.update_texts import get_update_texts


class UpdateDialogResult(Enum):
    """用户选择。"""

    UPDATE_NOW = auto()
    DISMISS = auto()
    CLOSE = auto()


class UpdateDialog(QDialog):
    """展示版本信息与 Release 说明，供自动/手动检查共用。"""

    _BUTTON_MIN_WIDTH = 128

    def __init__(
        self,
        offer: UpdateOffer,
        current_version: str,
        auto_mode: bool,
        parent=None,
    ):
        super().__init__(parent)
        self._offer = offer
        self._current_version = current_version or APP_VERSION
        self._auto_mode = auto_mode
        self._result = UpdateDialogResult.CLOSE
        self._intro_label: QLabel | None = None
        self._current_label: QLabel | None = None
        self._new_label: QLabel | None = None
        self._notes_edit: QTextEdit | None = None
        self._btn_update: QPushButton | None = None
        self._btn_later: QPushButton | None = None
        self.setMinimumWidth(480)
        self._setup_ui()
        self.apply_language(Settings().language)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._intro_label = QLabel(self)
        self._intro_label.setProperty("role", "section-title")
        self._intro_label.setWordWrap(True)
        layout.addWidget(self._intro_label)

        self._current_label = QLabel(self)
        layout.addWidget(self._current_label)

        self._new_label = QLabel(self)
        layout.addWidget(self._new_label)

        self._notes_edit = QTextEdit(self)
        self._notes_edit.setReadOnly(True)
        self._notes_edit.setMaximumHeight(120)
        layout.addWidget(self._notes_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_update = QPushButton(self)
        self._btn_update.clicked.connect(self._on_update)
        self._btn_update.setMinimumWidth(self._BUTTON_MIN_WIDTH)
        self._btn_update.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self._btn_update, 1)

        self._btn_later = QPushButton(self)
        self._btn_later.clicked.connect(self._on_later)
        self._btn_later.setMinimumWidth(self._BUTTON_MIN_WIDTH)
        self._btn_later.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_row.addWidget(self._btn_later, 1)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def apply_language(self, language: str) -> None:
        """刷新窗口与按钮文案。"""
        t = get_update_texts(language)
        self.setWindowTitle(t.dialog_title)
        if self._intro_label:
            self._intro_label.setText(t.dialog_intro)
        if self._current_label:
            self._current_label.setText(t.label_current.format(current=self._current_version))
        if self._new_label:
            self._new_label.setText(t.label_new.format(new=self._offer.version))
        if self._notes_edit:
            body = self._offer.release_notes.strip() or t.notes_placeholder
            self._notes_edit.setPlainText(body)
        if self._btn_update:
            self._btn_update.setText(t.btn_update)
        if self._btn_later:
            self._btn_later.setText(t.btn_later)
            self._btn_later.setVisible(self._auto_mode)

    def _on_update(self) -> None:
        self._result = UpdateDialogResult.UPDATE_NOW
        self.accept()

    def _on_later(self) -> None:
        self._result = UpdateDialogResult.DISMISS
        self.reject()

    def reject(self) -> None:
        """标题栏 X：视为关闭，不写 dismissed。"""
        self._result = UpdateDialogResult.CLOSE
        super().reject()

    @property
    def user_result(self) -> UpdateDialogResult:
        return self._result

    @property
    def offer(self) -> UpdateOffer:
        return self._offer
