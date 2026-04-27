"""工程列表面板。

支持多选、拖拽重新排序、添加/移除按钮。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QHBoxLayout, QMessageBox)
from PySide6.QtCore import Qt, Signal, QMimeData
from PySide6.QtGui import QDrag
from pathlib import Path
from ...models.project import Project
from ...config.settings import Settings

class ProjectPanel(QWidget):
    """左侧工程管理面板。

    使用 QListWidget 实现拖拽排序 (通过 mimeData 传递顺序)。
    """
    project_selected = Signal(list)  # 选中的 Project 路径列表
    project_added = Signal(Path)
    project_removed = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self.projects: list[Project] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("工程列表")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        # 按钮栏
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("添加工程")
        self.btn_remove = QPushButton("移除选中")
        self.btn_select_all = QPushButton("全选/反选")

        self.btn_add.clicked.connect(self._add_project)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_select_all.clicked.connect(self._toggle_select_all)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_select_all)
        layout.addLayout(btn_layout)

    def _on_selection_changed(self) -> None:
        selected = [item.data(Qt.UserRole) for item in self.list_widget.selectedItems() if item.data(Qt.UserRole)]
        self.project_selected.emit(selected)

    def load_projects(self, projects: list[Project]) -> None:
        self.projects = projects
        self.list_widget.clear()
        for project in projects:
            item = QListWidgetItem(project.name)
            item.setData(Qt.UserRole, str(project.path))
            self.list_widget.addItem(item)

    def _add_project(self) -> None:
        # TODO: 使用 QFileDialog 选择目录
        # 临时使用示例路径，后续在 main_window 中连接真实对话框
        test_path = Path("D:/workspace/unity/unity-client-2022")
        if test_path.exists():
            self.project_added.emit(test_path)

    def _remove_selected(self) -> None:
        selected = self.list_widget.selectedItems()
        if not selected:
            return
        if QMessageBox.question(self, "确认", "确定移除选中的工程吗？") == QMessageBox.Yes:
            for item in selected:
                path_str = item.data(Qt.UserRole)
                self.project_removed.emit(Path(path_str))
                self.list_widget.takeItem(self.list_widget.row(item))

    def _toggle_select_all(self) -> None:
        # 简单实现，后续完善
        pass

    def get_selected_project_paths(self) -> list[Path]:
        return [Path(item.data(Qt.UserRole)) for item in self.list_widget.selectedItems()]
