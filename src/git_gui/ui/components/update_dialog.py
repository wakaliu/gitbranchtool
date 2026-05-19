"""检查更新结果对话框。"""
from __future__ import annotations

import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ...core.update_service import UpdateCheckResult, preferred_download_url


class UpdateDialog(QDialog):
    """展示检查更新结果，并提供打开下载页/安装包入口。"""

    def __init__(
        self,
        result: UpdateCheckResult,
        *,
        language: str = "zh",
        parent=None,
    ):
        super().__init__(parent)
        self._result = result
        self._language = language
        self._setup_ui()

    def _is_en(self) -> bool:
        return self._language == "en"

    def _setup_ui(self) -> None:
        if self._result.status == "latest":
            self._setup_latest_ui()
            return
        if self._result.status == "error":
            self._setup_error_ui()
            return
        self._setup_update_ui()

    def _setup_latest_ui(self) -> None:
        if self._is_en():
            self.setWindowTitle("Check for Updates")
            text = f"You are on the latest version (v{self._result.current_version})."
            btn = "OK"
        else:
            self.setWindowTitle("检查更新")
            text = f"当前已是最新版本（v{self._result.current_version}）。"
            btn = "确定"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(text))
        ok = QPushButton(btn)
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(ok)
        layout.addLayout(row)
        self.resize(420, 120)

    def _setup_error_ui(self) -> None:
        if self._is_en():
            self.setWindowTitle("Check for Updates")
            title = "Unable to check for updates"
            btn = "OK"
        else:
            self.setWindowTitle("检查更新")
            title = "检查更新失败"
            btn = "确定"
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))
        layout.addWidget(QLabel(self._result.message))
        ok = QPushButton(btn)
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(ok)
        layout.addLayout(row)
        self.resize(460, 140)

    def _setup_update_ui(self) -> None:
        info = self._result.info
        assert info is not None
        if self._is_en():
            self.setWindowTitle("Update Available")
            headline = f"New version available: v{info.version}"
            if info.prerelease:
                headline += "\n(Pre-release — use with caution in production)"
            primary_label = (
                "Download Installer"
                if sys.platform == "win32"
                else "Open in Browser"
            )
            secondary_label = "View Release Page"
            close_label = "Close"
        else:
            self.setWindowTitle("发现新版本")
            headline = f"发现新版本：v{info.version}"
            if info.prerelease:
                headline += "\n（预发布测试版，生产环境请谨慎使用）"
            primary_label = "下载安装包" if sys.platform == "win32" else "在浏览器中查看"
            secondary_label = "打开 Release 页面"
            close_label = "关闭"

        layout = QVBoxLayout(self)
        title = QLabel(headline)
        title.setWordWrap(True)
        if info.prerelease:
            title.setProperty("role", "warning")
        layout.addWidget(title)

        if info.name and info.name != info.tag_name:
            layout.addWidget(QLabel(info.name))

        body = QTextBrowser()
        body.setPlainText((info.body or "").strip() or "—")
        body.setMaximumHeight(220)
        layout.addWidget(body)

        row = QHBoxLayout()
        btn_primary = QPushButton(primary_label)
        btn_primary.setProperty("role", "primary")
        btn_primary.clicked.connect(lambda: self._open_url(preferred_download_url(info)))
        row.addWidget(btn_primary)

        btn_release = QPushButton(secondary_label)
        btn_release.clicked.connect(lambda: self._open_url(info.release_page_url))
        row.addWidget(btn_release)

        btn_close = QPushButton(close_label)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        row.addStretch()
        layout.addLayout(row)
        self.resize(520, 360)

    def _open_url(self, url: str | None) -> None:
        if not url:
            if self._is_en():
                QMessageBox.warning(self, "Update", "No download link found for this platform.")
            else:
                QMessageBox.warning(self, "更新", "未找到适用于当前平台的下载链接。")
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            if self._is_en():
                QMessageBox.warning(self, "Update", "Failed to open the system browser.")
            else:
                QMessageBox.warning(self, "更新", "无法打开系统浏览器。")
