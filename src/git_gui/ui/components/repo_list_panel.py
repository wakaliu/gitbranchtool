"""仓库列表面板 (左侧操作区上半部分)。

包含顶部菜单栏 (全选/刷新/Fetch/新建拉线/一键瘦身) 和仓库列表。
支持多选和拖拽排序。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
                               QListWidgetItem, QLabel, QFrame)
from PySide6.QtCore import Qt, Signal
from pathlib import Path
from ...models.repository import GitRepository

class RepoListPanel(QWidget):
    """仓库列表 + 菜单栏组件。"""
    refresh_requested = Signal()
    fetch_requested = Signal(list)          # 选中的仓库路径列表
    switch_requested = Signal()             # 转到 OperationPanel 处理
    console_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.repositories: list[GitRepository] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 菜单栏 (对应图片中的全选/刷新/Fetch/新建拉线/一键瘦身)
        menu_frame = QFrame()
        menu_frame.setFrameShape(QFrame.StyledPanel)
        menu_layout = QHBoxLayout(menu_frame)

        self.btn_select_all = QPushButton("全选/反选")
        self.btn_refresh = QPushButton("刷新")
        self.btn_fetch = QPushButton("Fetch")
        self.btn_new_pull = QPushButton("新建拉线")
        self.btn_slim = QPushButton("一键瘦身")

        for btn in (self.btn_select_all, self.btn_refresh, self.btn_fetch,
                   self.btn_new_pull, self.btn_slim):
            menu_layout.addWidget(btn)

        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_fetch.clicked.connect(self._on_fetch_clicked)
        # 其他按钮信号后续在 main_window 连接

        layout.addWidget(menu_frame)

        # 标题
        title = QLabel("仓库列表")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.list_widget)

    def load_repositories(self, repos: list[GitRepository]) -> None:
        """加载仓库列表，工程根仓库默认排最前。"""
        self.repositories = repos
        self.list_widget.clear()
        for repo in repos:
            display = f"{repo.name} ({repo.current_branch})"
            if repo.is_dirty:
                display += " [已修改]"
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, str(repo.path))
            self.list_widget.addItem(item)

    def _on_fetch_clicked(self) -> None:
        selected = [Path(item.data(Qt.UserRole)) for item in self.list_widget.selectedItems()]
        if not selected:
            # 如果没有选中则使用全部
            selected = [r.path for r in self.repositories]
        self.fetch_requested.emit(selected)

    def get_selected_repo_paths(self) -> list[Path]:
        return [Path(item.data(Qt.UserRole)) for item in self.list_widget.selectedItems()]
