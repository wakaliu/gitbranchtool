"""工程列表面板。

支持多选、拖拽重新排序、添加/移除按钮。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QHBoxLayout, QMessageBox, QFileDialog)
from PySide6.QtCore import Qt, Signal
from pathlib import Path
from ...models.project import Project
from ...config.settings import Settings
from ..theme import get_icon

class ProjectPanel(QWidget):
    """左侧工程管理面板。

    使用 QListWidget 实现拖拽排序 (通过 mimeData 传递顺序)。
    """
    project_selected = Signal(list)  # 选中的 Project 路径列表
    project_added = Signal(Path)
    project_removed = Signal(Path)
    clone_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = Settings()
        self.projects: list[Project] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title_label = QLabel("工程列表")
        self.title_label.setProperty("role", "section-title")
        layout.addWidget(self.title_label)
        self.selection_hint_label = QLabel("未选择工程")
        self.selection_hint_label.setProperty("role", "secondary")
        layout.addWidget(self.selection_hint_label)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("projectList")
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setSpacing(4)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)
        self.empty_hint_label = QLabel("暂无工程，请先点击“添加工程”或“克隆新工程”。")
        self.empty_hint_label.setProperty("role", "secondary")
        self.empty_hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_hint_label)

        # 按钮栏
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("添加工程")
        self.btn_remove = QPushButton("移除选中")
        self.btn_clone = QPushButton("克隆工程")
        self.btn_add.setIcon(get_icon(self, "add"))
        self.btn_remove.setIcon(get_icon(self, "remove"))
        self.btn_clone.setIcon(get_icon(self, "clone"))

        self.btn_add.clicked.connect(self._add_project)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clone.clicked.connect(self.clone_requested.emit)

        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_remove)
        btn_layout.addWidget(self.btn_clone)
        layout.addLayout(btn_layout)
        self.apply_language(self.settings.language)

    def apply_language(self, language: str) -> None:
        """应用工程面板文案语言。"""
        if language == "en":
            self.title_label.setText("Projects")
            self.btn_add.setText("Add Project")
            self.btn_remove.setText("Remove Project")
            self.btn_clone.setText("Clone New Project")
            self.empty_hint_label.setText("No projects yet. Add or clone a project to get started.")
            self.selection_hint_label.setText("No project selected")
            return
        self.title_label.setText("工程列表")
        self.btn_add.setText("添加工程")
        self.btn_remove.setText("移除工程")
        self.btn_clone.setText("克隆新工程")
        self.empty_hint_label.setText("暂无工程，请先点击“添加工程”或“克隆新工程”。")
        self.selection_hint_label.setText("未选择工程")

    def _on_selection_changed(self) -> None:
        selected = [item.data(Qt.UserRole) for item in self.list_widget.selectedItems() if item.data(Qt.UserRole)]
        self._update_selected_project_hint(selected[0] if selected else None)
        self.project_selected.emit(selected)

    def load_projects(self, projects: list[Project]) -> None:
        self.projects = projects
        self.list_widget.clear()
        for project in projects:
            item = QListWidgetItem(project.name)
            item.setData(Qt.UserRole, str(project.path))
            item.setToolTip(str(project.path))
            self.list_widget.addItem(item)
        has_data = bool(projects)
        self.empty_hint_label.setVisible(not has_data)
        if not has_data:
            self._update_selected_project_hint(None)

    def select_project_by_path(self, project_path: Path) -> bool:
        """按路径选中工程；找到返回 True。"""
        target = str(project_path)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.UserRole) == target:
                self.list_widget.clearSelection()
                item.setSelected(True)
                self.list_widget.setCurrentItem(item)
                return True
        return False

    def select_first_project(self) -> None:
        """选中第一个工程（若存在）。"""
        if self.list_widget.count() > 0:
            self.list_widget.clearSelection()
            first_item = self.list_widget.item(0)
            if first_item:
                first_item.setSelected(True)
                self.list_widget.setCurrentItem(first_item)

    def _update_selected_project_hint(self, selected_path: str | None) -> None:
        """显示当前选中工程与仓库数，帮助用户快速确认操作上下文。"""
        if not selected_path:
            if self.settings.language == "en":
                self.selection_hint_label.setText("No project selected")
            else:
                self.selection_hint_label.setText("未选择工程")
            return
        for project in self.projects:
            if str(project.path) != selected_path:
                continue
            repo_count = len(project.repositories)
            if self.settings.language == "en":
                self.selection_hint_label.setText(f"Selected: {project.name} | {repo_count} repos")
            else:
                self.selection_hint_label.setText(f"当前选中：{project.name}（{repo_count} 个仓库）")
            return
        if self.settings.language == "en":
            self.selection_hint_label.setText("Selected project is unavailable")
        else:
            self.selection_hint_label.setText("当前选中工程不可用")

    def _add_project(self) -> None:
        """打开文件对话框选择目录作为新工程（非阻塞）。记住上次选择的目录。"""
        settings = Settings()
        start_dir = settings.get_last_added_dir()

        folder = QFileDialog.getExistingDirectory(
            self,
            "选择工程目录",
            str(start_dir),
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if folder:
            settings.save_last_added_dir(folder)
            self.project_added.emit(Path(folder))

    def _remove_selected(self) -> None:
        selected_rows = sorted(
            {self.list_widget.row(item) for item in self.list_widget.selectedItems()},
            reverse=True
        )
        if not selected_rows:
            return
        if QMessageBox.question(self, "确认", "确定移除选中的工程吗？") == QMessageBox.Yes:
            for row in selected_rows:
                item = self.list_widget.item(row)
                if not item:
                    continue
                path_str = item.data(Qt.UserRole)
                if path_str:
                    self.project_removed.emit(Path(path_str))
                self.list_widget.takeItem(row)

    def get_selected_project_paths(self) -> list[Path]:
        return [Path(item.data(Qt.UserRole)) for item in self.list_widget.selectedItems()]
