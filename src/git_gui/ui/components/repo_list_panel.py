"""仓库列表面板 (左侧操作区上半部分)。

包含顶部菜单栏 (全选/刷新/Fetch/新建拉线/一键瘦身) 和仓库列表。
支持多选和拖拽排序。
"""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
                               QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView)
from PySide6.QtCore import Qt, Signal, QUrl, QMimeData
from PySide6.QtGui import QDesktopServices, QDrag
from pathlib import Path
from ...models.repository import GitRepository

class ReorderableRepoTable(QTableWidget):
    """支持拖拽重排的仓库表格（第1行固定不可移动）。"""
    reorder_requested = Signal(int, int)  # source_row, target_row

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_row = -1
        self._mime_type = "application/x-gittool-repo-row"
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.MoveAction)

    def mousePressEvent(self, event):  # noqa: N802
        self._drag_row = self.rowAt(event.pos().y())
        super().mousePressEvent(event)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(self._mime_type):
            event.acceptProposedAction()
            return
        event.ignore()

    def startDrag(self, supported_actions):  # noqa: N802
        # 主仓库行固定在第一行，不允许拖动
        if self._drag_row < 0:
            self._drag_row = self.currentRow()
        if self._drag_row < 0:
            self._drag_row = self.rowAt(self.viewport().mapFromGlobal(self.cursor().pos()).y())
        if self._drag_row == 0:
            return
        if self._drag_row < 0:
            return
        mime = QMimeData()
        mime.setData(self._mime_type, str(self._drag_row).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragMoveEvent(self, event):  # noqa: N802
        if not event.mimeData().hasFormat(self._mime_type):
            event.ignore()
            return
        target = self.rowAt(event.position().toPoint().y())
        if target == 0:
            event.ignore()
            return
        event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        if not event.mimeData().hasFormat(self._mime_type):
            event.ignore()
            return
        try:
            source = int(bytes(event.mimeData().data(self._mime_type)).decode("utf-8"))
        except Exception:
            source = self._drag_row if self._drag_row >= 0 else self.currentRow()
        target = self.rowAt(event.position().toPoint().y())
        if target < 0:
            target = self.rowCount() - 1
        if source < 1 or target < 1:
            self._drag_row = -1
            event.ignore()
            return
        self.reorder_requested.emit(source, target)
        self._drag_row = -1
        event.acceptProposedAction()

class RepoListPanel(QWidget):
    """仓库列表 + 菜单栏组件。"""
    refresh_requested = Signal()
    fetch_requested = Signal(list)          # 选中的仓库路径列表
    switch_requested = Signal()             # 转到 OperationPanel 处理
    console_requested = Signal()
    order_changed = Signal(list)            # 当前顺序的仓库路径字符串列表

    def __init__(self, parent=None):
        super().__init__(parent)
        self.repositories: list[GitRepository] = []
        self._checked_state_by_path: dict[str, bool] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 标题（需在最上方，和其他区域表头统一）
        self.title_label = QLabel("仓库列表")
        self.title_label.setStyleSheet("font-weight: 700; font-size: 13px; color: #333333;")
        layout.addWidget(self.title_label)

        # 菜单栏 (对应图片中的全选/刷新/Fetch/新建拉线/一键瘦身)
        menu_frame = QFrame()
        menu_frame.setFrameShape(QFrame.StyledPanel)
        menu_layout = QHBoxLayout(menu_frame)

        self.btn_select_all = QPushButton("全选/反选")
        self.btn_refresh = QPushButton("刷新")
        self.btn_fetch = QPushButton("Fetch")
        self.btn_slim = QPushButton("一键瘦身")

        for btn in (self.btn_select_all, self.btn_refresh, self.btn_fetch, self.btn_slim):
            menu_layout.addWidget(btn)

        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        self.btn_fetch.clicked.connect(self._on_fetch_clicked)
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        # 其他按钮信号后续在 main_window 连接

        layout.addWidget(menu_frame)

        self.repo_table = ReorderableRepoTable()
        self.repo_table.setColumnCount(5)
        self.repo_table.setHorizontalHeaderLabels(["状态", "当前分支", "同步", "仓库名", "路径"])
        self.repo_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.repo_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.repo_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.repo_table.verticalHeader().setVisible(False)
        self.repo_table.horizontalHeader().setStretchLastSection(False)
        self.repo_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.repo_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.repo_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.repo_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.repo_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.repo_table.setColumnWidth(0, 56)
        self.repo_table.setColumnWidth(1, 230)
        self.repo_table.setColumnWidth(2, 100)
        self.repo_table.setColumnWidth(3, 160)
        self.repo_table.setColumnWidth(4, 520)
        self.repo_table.reorder_requested.connect(self._on_reorder_requested)
        layout.addWidget(self.repo_table)
        self.apply_language("zh")

    def load_repositories(self, repos: list[GitRepository]) -> None:
        """加载仓库表格，按需求显示状态/分支/同步/仓库名/路径。"""
        # 先保留当前勾选状态（按路径）
        self._capture_checked_state()
        self.repositories = repos
        self.repo_table.setRowCount(len(repos))
        for row, repo in enumerate(repos):
            sync_text = self._sync_text(repo.status, repo.ahead_count, repo.behind_count)
            status_item = QTableWidgetItem("")
            status_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            checked = self._checked_state_by_path.get(str(repo.path), True)
            status_item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            cells = [
                status_item,
                QTableWidgetItem(repo.current_branch or "HEAD"),
                QTableWidgetItem(sync_text),
                QTableWidgetItem(repo.name),
                QTableWidgetItem(""),
            ]
            for col, cell in enumerate(cells):
                if col in (0, 1, 2, 3):
                    cell.setTextAlignment(Qt.AlignCenter)
                self.repo_table.setItem(row, col, cell)
            self.repo_table.setCellWidget(row, 4, self._create_path_cell(repo.path))

    def apply_language(self, language: str) -> None:
        """应用仓库列表面板文案语言。"""
        if language == "en":
            self.title_label.setText("Repositories")
            self.btn_select_all.setText("Select/Invert")
            self.btn_refresh.setText("Refresh")
            self.btn_fetch.setText("Fetch")
            self.btn_slim.setText("Cleanup")
            self.repo_table.setHorizontalHeaderLabels(["State", "Branch", "Sync", "Repo", "Path"])
            return
        self.title_label.setText("仓库列表")
        self.btn_select_all.setText("全选/反选")
        self.btn_refresh.setText("刷新")
        self.btn_fetch.setText("Fetch")
        self.btn_slim.setText("一键瘦身")
        self.repo_table.setHorizontalHeaderLabels(["状态", "当前分支", "同步", "仓库名", "路径"])

    def _on_fetch_clicked(self) -> None:
        selected = self.get_selected_repo_paths()
        if not selected:
            # 如果没有选中则使用全部
            selected = [r.path for r in self.repositories]
        self.fetch_requested.emit(selected)

    def get_selected_repo_paths(self) -> list[Path]:
        rows = []
        for row in range(self.repo_table.rowCount()):
            item = self.repo_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                rows.append(row)
        if not rows:
            rows = sorted({index.row() for index in self.repo_table.selectionModel().selectedRows()})
        paths: list[Path] = []
        for row in rows:
            if 0 <= row < len(self.repositories):
                paths.append(self.repositories[row].path)
        return paths

    def _toggle_select_all(self) -> None:
        """全选/反选仓库勾选状态。"""
        row_count = self.repo_table.rowCount()
        if row_count == 0:
            return
        checked_rows = 0
        for row in range(row_count):
            item = self.repo_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                checked_rows += 1
        target_state = Qt.Unchecked if checked_rows == row_count else Qt.Checked
        for row in range(row_count):
            item = self.repo_table.item(row, 0)
            if item:
                item.setCheckState(target_state)

    @staticmethod
    def _sync_text(status: str, ahead_count: int = 0, behind_count: int = 0) -> str:
        if status == "synced":
            return "✓ 最新"
        if status == "behind":
            return f"↓ {behind_count}"
        if status == "ahead":
            return f"↑ {ahead_count}"
        if status == "diverged":
            return f"↕ {ahead_count}/{behind_count}"
        return "未知"

    def _create_path_cell(self, repo_path: Path) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        open_btn = QPushButton("开")
        open_btn.setToolTip("打开目录")
        open_btn.setFixedWidth(24)
        open_btn.clicked.connect(lambda _, p=repo_path: self._open_directory(p))

        path_label = QLabel(str(repo_path))
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout.addWidget(open_btn)
        layout.addWidget(path_label, 1)
        return container

    @staticmethod
    def _open_directory(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _capture_checked_state(self) -> None:
        state: dict[str, bool] = {}
        for row in range(self.repo_table.rowCount()):
            if row >= len(self.repositories):
                continue
            repo_path = str(self.repositories[row].path)
            item = self.repo_table.item(row, 0)
            state[repo_path] = bool(item and item.checkState() == Qt.Checked)
        self._checked_state_by_path = state

    def _on_reorder_requested(self, source: int, target: int) -> None:
        """处理拖拽重排，主仓库（第1行）固定不动。"""
        if not self.repositories:
            return
        if source < 1 or source >= len(self.repositories):
            return
        # 目标不能放到第1行之前
        target = max(1, min(target, len(self.repositories) - 1))
        if source == target:
            return
        self._capture_checked_state()
        moving = self.repositories.pop(source)
        if target > source:
            target -= 1
        self.repositories.insert(target, moving)
        self.load_repositories(self.repositories)
        self.repo_table.selectRow(target)
        self.order_changed.emit([str(r.path) for r in self.repositories])
