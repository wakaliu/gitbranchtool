"""右侧操作台面板。

包含目标分支输入、收藏、一键切线、Stash 选项、Git 控制台按钮和结果显示。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QCheckBox, QLabel, QGroupBox, QMessageBox)
from PySide6.QtCore import Qt, Signal
from pathlib import Path
from ...config.settings import Settings

class OperationPanel(QWidget):
    """操作台 (右侧)。

    一键切线是本工具核心功能。
    """
    switch_requested = Signal(str, bool)   # target_branch, stash
    console_requested = Signal()
    favorite_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self._current_target_branch = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 目标分支区域
        target_group = QGroupBox("目标分支")
        target_layout = QHBoxLayout(target_group)

        self.branch_input = QLineEdit()
        self.branch_input.setPlaceholderText("输入或粘贴分支名 (留空则使用当前分支最新节点)")
        self.btn_fill = QPushButton("填入")
        self.btn_favorite = QPushButton("收藏")

        self.btn_fill.clicked.connect(self._fill_from_repo)
        self.btn_favorite.clicked.connect(self.favorite_requested.emit)

        target_layout.addWidget(self.branch_input, 4)
        target_layout.addWidget(self.btn_fill)
        target_layout.addWidget(self.btn_favorite)
        layout.addWidget(target_group)

        # 一键切线
        self.btn_switch = QPushButton("一键切线 (Switch)")
        self.btn_switch.setStyleSheet("font-size: 16px; padding: 12px; background-color: #0078d4; color: white; font-weight: bold;")
        self.btn_switch.clicked.connect(self._on_switch_clicked)
        layout.addWidget(self.btn_switch)

        # 选项
        options_layout = QHBoxLayout()

        self.chk_stash = QCheckBox("Stash 本地修改")
        self.chk_stash.setChecked(False)  # 默认不勾选

        self.btn_console = QPushButton("打开 Git 控制台")
        self.btn_console.clicked.connect(self.console_requested.emit)

        options_layout.addWidget(self.chk_stash)
        options_layout.addWidget(self.btn_console)
        layout.addLayout(options_layout)

        # 结果显示
        result_group = QGroupBox("Git 执行结果")
        result_layout = QVBoxLayout(result_group)
        self.result_label = QLabel("等待操作...")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("background-color: #f0f0f0; padding: 10px; border-radius: 4px;")
        result_layout.addWidget(self.result_label)
        layout.addWidget(result_group)

        layout.addStretch()

    def _on_switch_clicked(self) -> None:
        target = self.branch_input.text().strip()
        stash = self.chk_stash.isChecked()
        self.switch_requested.emit(target, stash)

    def _fill_from_repo(self) -> None:
        """从当前选中仓库获取当前分支填入 (多选时取第一个)。"""
        # 实际逻辑由 MainWindow 提供当前选中仓库
        # 这里触发信号让主窗口处理
        self.branch_input.setText(self.settings.get("paths.default_branch", "develop"))

    def update_result(self, text: str, is_success: bool = True) -> None:
        color = "#28a745" if is_success else "#dc3545"
        self.result_label.setStyleSheet(f"background-color: #f0f0f0; padding: 10px; border-radius: 4px; color: {color};")
        self.result_label.setText(text)
