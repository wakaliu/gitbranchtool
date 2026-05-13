"""右侧操作台面板。

包含目标分支输入、收藏、一键切线、Stash 选项、Git 控制台按钮和结果显示。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
                               QCheckBox, QLabel, QGroupBox, QPlainTextEdit, QSizePolicy)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from pathlib import Path
from ...config.settings import Settings
from ..theme import get_icon

class OperationPanel(QWidget):
    """操作台 (右侧)。

    一键切线是本工具核心功能。
    """
    switch_requested = Signal(str, bool)   # target_branch, stash
    console_requested = Signal()
    favorite_requested = Signal()
    fill_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self._current_target_branch = ""
        self._last_summary_raw: str = ""
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title_label = QLabel("操作台")
        self.title_label.setProperty("role", "section-title")
        layout.addWidget(self.title_label)

        # 目标分支区域
        target_group = QGroupBox("目标分支")
        target_layout = QHBoxLayout(target_group)
        target_layout.setContentsMargins(8, 18, 8, 8)
        target_layout.setSpacing(6)

        self.branch_input = QLineEdit()
        self.branch_input.setPlaceholderText("输入或粘贴分支名 (留空则使用当前分支最新节点)")
        self.btn_fill = QPushButton("填入")
        self.btn_favorite = QPushButton("收藏")
        self.btn_fill.setIcon(get_icon(self, "fill"))
        self.btn_favorite.setIcon(get_icon(self, "favorite"))

        self.btn_fill.clicked.connect(self.fill_requested.emit)
        self.btn_favorite.clicked.connect(self.favorite_requested.emit)

        target_layout.addWidget(self.branch_input, 4)
        target_layout.addWidget(self.btn_fill)
        target_layout.addWidget(self.btn_favorite)
        layout.addWidget(target_group)

        # 一键切线
        self.btn_switch = QPushButton("一键切线 (Switch)")
        self.btn_switch.setProperty("role", "primary")
        self.btn_switch.setIcon(get_icon(self, "switch"))
        self.btn_switch.clicked.connect(self._on_switch_clicked)
        layout.addWidget(self.btn_switch)

        # 选项
        options_layout = QHBoxLayout()

        self.chk_stash = QCheckBox("Stash 本地修改")
        self.chk_stash.setChecked(True)

        self.btn_console = QPushButton("打开 Git 控制台")
        self.btn_console.setIcon(get_icon(self, "console"))
        self.btn_console.clicked.connect(self.console_requested.emit)

        options_layout.addWidget(self.chk_stash)
        options_layout.addWidget(self.btn_console)
        layout.addLayout(options_layout)
        layout.addStretch()

        # 结果显示
        result_group = QGroupBox("Git 执行结果")
        result_layout = QVBoxLayout(result_group)
        result_layout.setContentsMargins(8, 18, 8, 8)
        result_layout.setSpacing(6)
        result_tools_layout = QHBoxLayout()
        self.result_summary_label = QLabel("等待操作")
        self.result_summary_label.setProperty("role", "secondary")
        # 单行摘要若含超长路径/URL，会抬高 QLabel 的 minimumSizeHint，横向 QSplitter 为满足最小宽度会改比例。
        self.result_summary_label.setWordWrap(True)
        self.result_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        result_tools_layout.addWidget(self.result_summary_label, 1)
        result_tools_layout.addStretch()
        self.btn_clear_result = QPushButton("清")
        self.btn_clear_result.setProperty("role", "compact")
        self.btn_clear_result.setIcon(get_icon(self, "clear"))
        self.btn_clear_result.setFixedHeight(24)
        self.btn_clear_result.setToolTip("清理执行结果")
        self.btn_clear_result.clicked.connect(self.clear_result)
        result_tools_layout.addWidget(self.btn_clear_result)
        result_layout.addLayout(result_tools_layout)
        self.result_label = QPlainTextEdit()
        self.result_label.setReadOnly(True)
        self.result_label.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.result_label.setPlaceholderText("等待操作...")
        self.result_label.document().setMaximumBlockCount(200)
        self.result_label.setFixedHeight(86)
        result_layout.addWidget(self.result_label)
        layout.addSpacing(6)
        layout.addWidget(result_group)
        self.target_group = target_group
        self.result_group = result_group
        self.apply_language(self.settings.language)

    def _on_switch_clicked(self) -> None:
        target = self.branch_input.text().strip()
        stash = self.chk_stash.isChecked()
        self.switch_requested.emit(target, stash)

    def set_target_branch(self, branch: str) -> None:
        """将目标分支输入框设置为指定分支。"""
        self.branch_input.setText(branch)

    def apply_language(self, language: str) -> None:
        """应用操作台文案语言。"""
        if language == "en":
            self.title_label.setText("Actions")
            self.target_group.setTitle("Target Branch")
            self.branch_input.setPlaceholderText("Enter or paste branch name (empty means use latest commit of current branch)")
            self.btn_fill.setText("Fill")
            self.btn_favorite.setText("Favorite")
            self.btn_switch.setText("Switch Branch")
            self.chk_stash.setText("Stash local changes")
            self.btn_console.setText("Open Git Console")
            self.result_group.setTitle("Git Results")
            self.btn_clear_result.setText("Clear")
            self.btn_clear_result.setToolTip("Clear results")
            return
        self.title_label.setText("操作台")
        self.target_group.setTitle("目标分支")
        self.branch_input.setPlaceholderText("输入或粘贴分支名 (留空则使用当前分支最新节点)")
        self.btn_fill.setText("填入")
        self.btn_favorite.setText("收藏")
        self.btn_switch.setText("一键切线 (Switch)")
        self.chk_stash.setText("Stash 本地修改")
        self.btn_console.setText("打开 Git 控制台")
        self.result_group.setTitle("Git 执行结果")
        self.btn_clear_result.setText("清空")
        self.btn_clear_result.setToolTip("清理执行结果")

    def _summary_display_text(self, summary: str) -> str:
        """将首行摘要限制在可用宽度内，避免撑开操作台导致分割条比例漂移。"""
        if not summary.strip():
            return "等待操作"
        panel_w = max(self.width(), 0)
        avail = panel_w - 32 if panel_w > 160 else 420
        avail = max(int(avail), 200)
        fm = QFontMetrics(self.result_summary_label.font())
        return fm.elidedText(summary.strip(), Qt.TextElideMode.ElideRight, avail)

    def update_result(self, text: str, is_success: bool = True) -> None:
        summary = text.splitlines()[0].strip() if text else ""
        self._last_summary_raw = summary
        raw_summary = summary or "等待操作"
        self.result_summary_label.setText(self._summary_display_text(raw_summary))
        self.result_summary_label.setToolTip(raw_summary if summary else "")
        self.result_summary_label.setProperty("role", "success" if is_success else "danger")
        self.result_summary_label.style().unpolish(self.result_summary_label)
        self.result_summary_label.style().polish(self.result_summary_label)
        self.result_label.setProperty("role", "success" if is_success else "danger")
        self.result_label.style().unpolish(self.result_label)
        self.result_label.style().polish(self.result_label)
        self.result_label.appendPlainText(text)
        self.result_label.verticalScrollBar().setValue(self.result_label.verticalScrollBar().maximum())

    def clear_result(self) -> None:
        """清空执行结果，避免新旧批次日志混在一起。"""
        self.result_summary_label.setText("等待操作")
        self.result_summary_label.setToolTip("")
        self._last_summary_raw = ""
        self.result_summary_label.setProperty("role", "secondary")
        self.result_summary_label.style().unpolish(self.result_summary_label)
        self.result_summary_label.style().polish(self.result_summary_label)
        self.result_label.setProperty("role", "")
        self.result_label.style().unpolish(self.result_label)
        self.result_label.style().polish(self.result_label)
        self.result_label.clear()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._last_summary_raw:
            self.result_summary_label.setText(self._summary_display_text(self._last_summary_raw))
        """重置一键切线按钮状态。

        在进度对话框收尾后主线程同步调用即可；不再使用 QTimer，避免与对话框
        销毁顺序叠加产生额外事件导致不稳定。
        """
        try:
            self.btn_switch.setEnabled(True)
        except Exception:
            if hasattr(self, "btn_switch"):
                self.btn_switch.setEnabled(True)
