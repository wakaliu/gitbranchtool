"""Git 控制台对话框 (图8)。

允许用户输入任意 git 命令，对当前选中仓库 (或第一个) 执行。
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
                               QPushButton, QLabel, QMessageBox)
from PySide6.QtCore import Qt, Signal
from ...core.git_manager import GitManager
from pathlib import Path

class GitConsoleDialog(QDialog):
    """简单 Git 命令行控制台。"""
    def __init__(self, repo_path: Path = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Git 控制台")
        self.setMinimumSize(700, 500)
        self.repo_path = repo_path or Path.cwd()
        self.git_manager = GitManager()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        QLabel(f"当前仓库: {self.repo_path.name}", self).setStyleSheet("font-weight: bold;")

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("输入 git 命令 (例如: status, log --oneline -10)")
        self.btn_run = QPushButton("执行")
        self.btn_clear = QPushButton("清空")
        self.btn_close = QPushButton("关闭")

        self.btn_run.clicked.connect(self._run_command)
        self.btn_clear.clicked.connect(self.output.clear)
        self.btn_close.clicked.connect(self.accept)

        cmd_layout.addWidget(self.cmd_input, 4)
        cmd_layout.addWidget(self.btn_run)
        cmd_layout.addWidget(self.btn_clear)
        layout.addLayout(cmd_layout)
        layout.addWidget(self.btn_close)

        # 欢迎信息
        self.output.append("欢迎使用 Git 控制台。\n当前仓库: " + str(self.repo_path) + "\n输入命令后点击执行。\n")

    def _run_command(self) -> None:
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return

        self.output.append(f"> {cmd}")
        result = self.git_manager.run_arbitrary_command(self.repo_path, cmd)
        self.output.append(result)
        self.output.append("-" * 60)
        self.cmd_input.clear()
