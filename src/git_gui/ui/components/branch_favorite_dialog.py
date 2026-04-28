"""分支收藏对话框 (图7)。

显示常用分支，支持添加/删除/选择。
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton,
                               QLineEdit, QLabel, QMessageBox)
from PySide6.QtCore import Qt, Signal
from ...config.settings import Settings

class BranchFavoriteDialog(QDialog):
    """分支收藏管理。"""
    branch_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("收藏的分支")
        self.settings = Settings()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.setMinimumSize(320, 360)

        self.title_label = QLabel("常用分支收藏 (双击选择):", self)
        layout.addWidget(self.title_label)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(200)
        self.list_widget.itemDoubleClicked.connect(self._select_branch)
        layout.addWidget(self.list_widget)

        # 添加新分支
        add_layout = QHBoxLayout()
        self.new_branch_input = QLineEdit()
        self.new_branch_input.setPlaceholderText("输入新分支名")
        self.btn_add = QPushButton("添加")
        self.btn_remove = QPushButton("删除选中")
        self.btn_close = QPushButton("关闭")

        self.btn_add.clicked.connect(self._add_branch)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_close.clicked.connect(self.accept)

        add_layout.addWidget(self.new_branch_input)
        add_layout.addWidget(self.btn_add)
        layout.addLayout(add_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

        self._load_favorites()

    def _load_favorites(self) -> None:
        self.list_widget.clear()
        favorites = self.settings.get("favorites.branches", ["develop", "main"])
        for b in favorites:
            self.list_widget.addItem(b)

    def _add_branch(self) -> None:
        branch = self.new_branch_input.text().strip()
        if branch:
            current = self.settings.get("favorites.branches", [])
            if branch not in current:
                current.append(branch)
                self.settings.set("favorites.branches", current)
                self._load_favorites()
            self.new_branch_input.clear()

    def _remove_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item:
            branch = item.text()
            current = self.settings.get("favorites.branches", [])
            if branch in current:
                current.remove(branch)
                self.settings.set("favorites.branches", current)
                self._load_favorites()

    def _select_branch(self, item) -> None:
        self.branch_selected.emit(item.text())
        self.accept()
