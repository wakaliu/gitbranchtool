"""反馈对话框。

支持文字描述 + 图片上传，提交到 GitHub Issues。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
                               QPushButton, QFileDialog, QListWidget, QMessageBox)
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from pathlib import Path
from ...utils.github_issue import GitHubIssueReporter
from ...config.settings import Settings
from ...config.constants import APP_VERSION

class FeedbackDialog(QDialog):
    """用户反馈对话框。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("反馈建议")
        self.setMinimumSize(500, 400)
        self.reporter = GitHubIssueReporter()
        self.image_paths: list[Path] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("请描述您遇到的问题或改进建议 (可附截图):", self)
        title.setProperty("role", "section-title")
        layout.addWidget(title)
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("例如：切换分支时提示 lock 文件存在...")
        layout.addWidget(self.text_edit)

        # 图片列表
        layout.addWidget(QLabel("附加图片 (可选):"))
        self.image_list = QListWidget()
        layout.addWidget(self.image_list)

        btn_layout = QHBoxLayout()
        self.btn_add_image = QPushButton("添加图片")
        self.btn_submit = QPushButton("提交到 GitHub Issues")
        self.btn_submit.setProperty("role", "primary")
        self.btn_cancel = QPushButton("取消")

        self.btn_add_image.clicked.connect(self._add_image)
        self.btn_submit.clicked.connect(self._submit)
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_add_image)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_submit)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def _add_image(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", "Images (*.png *.jpg *.jpeg)")
        for f in files:
            path = Path(f)
            if path not in self.image_paths:
                self.image_paths.append(path)
                self.image_list.addItem(path.name)

    def _submit(self) -> None:
        text = self.text_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入反馈内容")
            return

        version = Settings().get("app.version", APP_VERSION)
        success, err_msg, browser_url = self.reporter.submit_feedback(
            title=f"用户反馈 - v{version}",
            body=text,
            image_paths=self.image_paths,
        )

        if success:
            QMessageBox.information(self, "成功", "反馈已提交到 GitHub Issues！感谢您的支持。")
            self.accept()
        else:
            self._show_submit_failed(err_msg or "提交失败，原因未知。", browser_url)

    def _show_submit_failed(self, err_msg: str, browser_url: Optional[str]) -> None:
        """API 失败时提示；若可解析出网页版 Issues 地址，提供浏览器打开（Qt 跨平台）。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("提交失败")
        box.setText(err_msg)
        box.setStandardButtons(QMessageBox.NoButton)
        btn_open = None
        if browser_url:
            lang = Settings().get("app.language", "zh")
            open_label = "Open in browser (Issues)" if lang == "en" else "在浏览器中打开 Issues"
            btn_open = box.addButton(open_label, QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if btn_open is not None and box.clickedButton() == btn_open:
            QDesktopServices.openUrl(QUrl(browser_url))
