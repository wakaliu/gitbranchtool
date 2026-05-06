"""设置对话框。

支持切换语言 (中/英) 和主题 (浅色/深色)，以及 GitHub Token 的钥匙串保存。
"""
import os

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QGroupBox, QMessageBox, QLineEdit, QCheckBox)
from PySide6.QtCore import Signal
from ...config.settings import Settings
from ...utils import credential_store

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

        gh_group = QGroupBox("GitHub 反馈 (Issues)")
        gh_layout = QVBoxLayout(gh_group)
        self.lbl_token_status = QLabel()
        self.lbl_token_status.setWordWrap(True)
        self.lbl_token_status.setProperty("role", "secondary")
        gh_layout.addWidget(self.lbl_token_status)
        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("输入新 Token 以保存；留空则保留已有配置")
        self.token_edit.setEchoMode(QLineEdit.Password)
        gh_layout.addWidget(self.token_edit)
        self.chk_keyring = QCheckBox("保存到系统钥匙串（推荐，明文不写入 config）")
        self.chk_keyring.setChecked(True)
        self.chk_keyring.setToolTip("Windows：凭据管理器；macOS：钥匙串访问")
        gh_layout.addWidget(self.chk_keyring)
        row_gh_btn = QHBoxLayout()
        self.btn_clear_token = QPushButton("清除已保存的 Token")
        self.btn_clear_token.clicked.connect(self._clear_github_token)
        row_gh_btn.addWidget(self.btn_clear_token)
        row_gh_btn.addStretch()
        gh_layout.addLayout(row_gh_btn)
        layout.addWidget(gh_group)
        self._gh_group = gh_group
        self._refresh_token_status_ui()

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

    def _refresh_token_status_ui(self) -> None:
        """展示当前 Token 来源，避免误会在输入框中看到已保存的明文。"""
        if credential_store.get_github_token():
            self.lbl_token_status.setText("当前状态：已使用系统钥匙串保存 Token（界面不显示明文）。")
        elif (self.settings.get("github.token") or "").strip():
            self.lbl_token_status.setText(
                "当前状态：Token 写在 config.yaml 中，若仓库可公开请勿提交该文件。"
            )
        elif os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get(
            "GIT_GUI_GITHUB_TOKEN", ""
        ).strip():
            self.lbl_token_status.setText("当前状态：将使用环境变量中的 Token。")
        else:
            self.lbl_token_status.setText("当前状态：未检测到已保存的 Token。")

        kr_ok = credential_store.is_keyring_available()
        self.chk_keyring.setEnabled(kr_ok)
        if not kr_ok:
            self.chk_keyring.setChecked(False)
            self.chk_keyring.setToolTip("未安装 keyring 或无可用后端，请 pip install keyring 或改用环境变量 / config")

    def _clear_github_token(self) -> None:
        credential_store.delete_github_token()
        self.settings.set("github.token", "")
        self.token_edit.clear()
        self._refresh_token_status_ui()
        QMessageBox.information(self, "已清除", "已移除钥匙串与配置文件中的 GitHub Token。")

    def _save_github_token_if_needed(self) -> bool:
        """若用户填写了 Token，按选项写入钥匙串或 config。返回是否应继续保存其它设置。"""
        raw = self.token_edit.text().strip()
        if not raw:
            return True
        use_keyring = self.chk_keyring.isChecked() and credential_store.is_keyring_available()
        if use_keyring:
            if credential_store.set_github_token(raw):
                self.settings.set("github.token", "")
                return True
            QMessageBox.warning(
                self,
                "保存失败",
                "无法写入系统钥匙串。可改用环境变量 GITHUB_TOKEN，或取消勾选后写入 config（不推荐纳入版本库）。",
            )
            return False
        credential_store.delete_github_token()
        self.settings.set("github.token", raw)
        return True

    def _save_and_apply(self) -> None:
        if not self._save_github_token_if_needed():
            return
        lang_idx = self.lang_combo.currentIndex()
        theme_idx = self.theme_combo.currentIndex()

        new_lang = "zh" if lang_idx == 0 else "en"
        new_theme = "light" if theme_idx == 0 else "dark"

        self.settings.set("app.language", new_lang)
        self.settings.set("app.theme", new_theme)

        self.settings_changed.emit()
        self._refresh_token_status_ui()
        QMessageBox.information(self, "成功", "设置已保存，重启后部分更改生效。")
        self.accept()
