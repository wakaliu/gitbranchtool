"""设置对话框。

支持切换语言 (中/英) 和主题 (浅色/深色)。
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QGroupBox, QMessageBox)
from PySide6.QtCore import Qt, Signal
from ...config.settings import Settings
from ...config.constants import SUPPORTED_LANGUAGES, SUPPORTED_THEMES

class SettingsDialog(QDialog):
    """设置对话框。

    更改后立即应用主题和语言 (通过信号通知主窗口)。
    """
    settings_changed = Signal()  # 通知主窗口重新加载主题/翻译

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.settings = Settings()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 语言
        lang_group = QGroupBox("语言 / Language")
        lang_layout = QHBoxLayout(lang_group)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["中文 (简体)", "English"])
        self.lang_combo.setCurrentIndex(0 if self.settings.language == "zh" else 1)
        lang_layout.addWidget(QLabel("界面语言:"))
        lang_layout.addWidget(self.lang_combo)
        layout.addWidget(lang_group)

        # 主题
        theme_group = QGroupBox("主题 / Theme")
        theme_layout = QHBoxLayout(theme_group)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["浅色 (Light)", "深色 (Dark)"])
        self.theme_combo.setCurrentIndex(0 if self.settings.theme == "light" else 1)
        theme_layout.addWidget(QLabel("界面主题:"))
        theme_layout.addWidget(self.theme_combo)
        layout.addWidget(theme_group)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("保存并应用")
        self.btn_save.setProperty("role", "primary")
        self.btn_cancel = QPushButton("取消")

        self.btn_save.clicked.connect(self._save_and_apply)
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def _save_and_apply(self) -> None:
        lang_idx = self.lang_combo.currentIndex()
        theme_idx = self.theme_combo.currentIndex()

        new_lang = "zh" if lang_idx == 0 else "en"
        new_theme = "light" if theme_idx == 0 else "dark"

        self.settings.set("app.language", new_lang)
        self.settings.set("app.theme", new_theme)

        self.settings_changed.emit()
        QMessageBox.information(self, "成功", "设置已保存，重启后部分更改生效。")
        self.accept()
