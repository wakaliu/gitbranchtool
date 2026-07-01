"""仓库瘦身选择对话框。"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config.settings import Settings
from ...models.repository import GitRepository
from ...utils.file_utils import (
    _path_has_entries,
    format_bytes,
    get_directory_size,
    normalize_repo_path_key,
    paths_refer_to_same_location,
    resolve_primary_repository_path,
)
from ...utils.logger import write_error_log


class SlimRepoDialog(QDialog):
    """展示各仓库磁盘占用并选择瘦身目标。"""

    slim_confirmed = Signal(list)
    scan_item_ready = Signal(str, str)
    scan_batch_finished = Signal()
    scan_progress = Signal(int, int, str)

    def __init__(
        self,
        parent=None,
        repositories: list[GitRepository] | None = None,
        project_root: Path | None = None,
    ):
        super().__init__(parent)
        self.settings = Settings()
        self.repositories = list(repositories or [])
        self._project_root = project_root
        self._primary_repo_path = resolve_primary_repository_path(
            project_root, self.repositories
        ) if project_root else None
        self._root_repo_key = (
            normalize_repo_path_key(self._primary_repo_path)
            if self._primary_repo_path
            else ""
        )
        self._language = self.settings.language
        self._size_by_path: dict[str, int] = {}
        self._scan_thread: threading.Thread | None = None
        self._scan_cancelled = False
        self._scan_generation = 0
        self._row_checkboxes: list[QCheckBox] = []
        self._setup_ui()
        self.apply_language(self._language)
        self.scan_item_ready.connect(self._on_scan_item_ready, Qt.ConnectionType.QueuedConnection)
        self.scan_batch_finished.connect(self._on_scan_batch_finished, Qt.ConnectionType.QueuedConnection)
        self.scan_progress.connect(self._on_scan_progress, Qt.ConnectionType.QueuedConnection)
        self._populate_table()
        self._start_size_scan()

    def _setup_ui(self) -> None:
        self.setMinimumSize(720, 480)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.hint_label = QLabel()
        self.hint_label.setProperty("role", "secondary")
        self.hint_label.setWordWrap(True)
        root_layout.addWidget(self.hint_label)

        toolbar = QHBoxLayout()
        self.btn_select_all = QPushButton()
        self.btn_select_all.clicked.connect(self._toggle_select_all)
        self.btn_refresh_sizes = QPushButton()
        self.btn_refresh_sizes.clicked.connect(self._start_size_scan)
        toolbar.addWidget(self.btn_select_all)
        toolbar.addWidget(self.btn_refresh_sizes)
        toolbar.addStretch()
        root_layout.addLayout(toolbar)

        self.repo_table = QTableWidget()
        self.repo_table.setColumnCount(5)
        self.repo_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.repo_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.repo_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.repo_table.setColumnWidth(0, 52)
        root_layout.addWidget(self.repo_table, 1)

        self.total_size_label = QLabel()
        self.total_size_label.setProperty("role", "secondary")
        root_layout.addWidget(self.total_size_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_cancel = QPushButton()
        self.btn_slim = QPushButton()
        for btn in (self.btn_cancel, self.btn_slim):
            btn.setFixedSize(132, 36)
        self.btn_cancel.setProperty("role", "dialog-action")
        self.btn_slim.setProperty("role", "dialog-action-primary")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_slim.clicked.connect(self._on_slim_clicked)
        self.btn_slim.setEnabled(False)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_slim)
        root_layout.addLayout(btn_row)

    @staticmethod
    def _create_centered_checkbox(checked: bool = True) -> tuple[QWidget, QCheckBox]:
        """在单元格内居中放置勾选框。"""
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        layout.addWidget(checkbox)
        return wrapper, checkbox

    def _is_root_repo(self, repo: GitRepository) -> bool:
        if not self._primary_repo_path:
            return False
        return paths_refer_to_same_location(repo.path, self._primary_repo_path)

    def _populate_table(self) -> None:
        self.repo_table.setRowCount(len(self.repositories))
        self._row_checkboxes.clear()
        for row, repo in enumerate(self.repositories):
            is_root_repo = self._is_root_repo(repo)
            wrapper, checkbox = self._create_centered_checkbox(checked=not is_root_repo)
            if is_root_repo:
                checkbox.setEnabled(False)
                checkbox.setToolTip(
                    "Project root cannot be slimmed"
                    if self._language == "en"
                    else "工程根目录不支持瘦身"
                )
            self._row_checkboxes.append(checkbox)
            branch_item = QTableWidgetItem(repo.current_branch or "HEAD")
            branch_item.setTextAlignment(Qt.AlignCenter)
            size_item = QTableWidgetItem(self._calculating_text())
            size_item.setTextAlignment(Qt.AlignCenter)
            name_item = QTableWidgetItem(repo.name)
            name_item.setTextAlignment(Qt.AlignCenter)
            path_item = QTableWidgetItem(str(repo.path))
            self.repo_table.setCellWidget(row, 0, wrapper)
            self.repo_table.setItem(row, 1, name_item)
            self.repo_table.setItem(row, 2, branch_item)
            self.repo_table.setItem(row, 3, size_item)
            self.repo_table.setItem(row, 4, path_item)
        self._update_total_size_label()

    def _calculating_text(self) -> str:
        return "Calculating..." if self._language == "en" else "计算中…"

    def _failed_text(self) -> str:
        return "Failed" if self._language == "en" else "统计失败"

    def _missing_text(self) -> str:
        return "Missing" if self._language == "en" else "路径不存在"

    def _format_size_for_repo(self, repo: GitRepository, size: int) -> str:
        if not repo.path.exists():
            return self._missing_text()
        if size <= 0 and _path_has_entries(repo.path):
            return self._failed_text()
        return format_bytes(size)

    def _row_for_path(self, repo_path: str) -> int:
        target = normalize_repo_path_key(repo_path)
        for row, repo in enumerate(self.repositories):
            if normalize_repo_path_key(repo.path) == target:
                return row
        return -1

    def _start_size_scan(self) -> None:
        if self._scan_thread and self._scan_thread.is_alive():
            self._scan_cancelled = True
            self._scan_thread.join(timeout=1.0)
        self._scan_cancelled = False
        self._scan_generation += 1
        generation = self._scan_generation
        self._size_by_path.clear()
        self.btn_refresh_sizes.setEnabled(False)
        self.btn_slim.setEnabled(False)
        for row in range(self.repo_table.rowCount()):
            item = self.repo_table.item(row, 3)
            if item:
                item.setText(self._calculating_text())
        repos = sorted(
            list(self.repositories),
            key=lambda repo: str(repo.path).count(os.sep),
            reverse=True,
        )
        total = len(repos)

        def scan_worker() -> None:
            for index, repo in enumerate(repos, start=1):
                if self._scan_cancelled or generation != self._scan_generation:
                    break
                self.scan_progress.emit(index, total, repo.name)
                try:
                    size = get_directory_size(repo.path)
                except Exception as exc:
                    write_error_log("仓库磁盘统计异常", f"repo={repo.path}\n{exc}")
                    size = 0
                if self._scan_cancelled or generation != self._scan_generation:
                    break
                self.scan_item_ready.emit(normalize_repo_path_key(repo.path), str(size))
            if not self._scan_cancelled and generation == self._scan_generation:
                self.scan_batch_finished.emit()

        self._scan_thread = threading.Thread(target=scan_worker, daemon=True)
        self._scan_thread.start()

    def _on_scan_progress(self, index: int, total: int, repo_name: str) -> None:
        if self._language == "en":
            self.total_size_label.setText(f"Scanning ({index}/{total}): {repo_name}...")
        else:
            self.total_size_label.setText(f"正在统计 ({index}/{total})：{repo_name}...")

    def _on_scan_item_ready(self, repo_path: str, size_text: str) -> None:
        try:
            size = int(size_text)
        except ValueError:
            size = 0
        self._size_by_path[repo_path] = size
        row = self._row_for_path(repo_path)
        if row >= 0:
            repo = self.repositories[row]
            item = self.repo_table.item(row, 3)
            if item:
                item.setText(self._format_size_for_repo(repo, size))
        self._update_total_size_label()

    def _on_scan_batch_finished(self) -> None:
        self.btn_refresh_sizes.setEnabled(True)
        self.btn_slim.setEnabled(True)
        self._update_total_size_label()

    def _update_total_size_label(self) -> None:
        scanned = len(self._size_by_path)
        pending = max(0, len(self.repositories) - scanned)
        root_key = normalize_repo_path_key(self._project_root) if self._project_root else ""
        root_size = self._size_by_path.get(root_key) if root_key else None
        if self._language == "en":
            suffix = f" ({scanned}/{len(self.repositories)} repos scanned)" if pending else ""
            if root_size is None:
                self.total_size_label.setText(f"Project disk usage: calculating...{suffix}")
            else:
                self.total_size_label.setText(
                    f"Project disk usage (root folder): {format_bytes(root_size)}{suffix}"
                )
        else:
            suffix = f"（已统计 {scanned}/{len(self.repositories)} 个仓库）" if pending else ""
            if root_size is None:
                self.total_size_label.setText(f"工程磁盘占用：计算中…{suffix}")
            else:
                self.total_size_label.setText(
                    f"工程磁盘占用（项目根目录）：{format_bytes(root_size)}{suffix}"
                )

    def _toggle_select_all(self) -> None:
        selectable = [cb for i, cb in enumerate(self._row_checkboxes) if cb.isEnabled()]
        if not selectable:
            return
        all_checked = all(cb.isChecked() for cb in selectable)
        target = not all_checked
        for checkbox in selectable:
            checkbox.setChecked(target)

    def _get_selected_repositories(self) -> list[GitRepository]:
        selected: list[GitRepository] = []
        for row, checkbox in enumerate(self._row_checkboxes):
            if (
                checkbox.isEnabled()
                and checkbox.isChecked()
                and row < len(self.repositories)
            ):
                selected.append(self.repositories[row])
        return selected

    def _on_slim_clicked(self) -> None:
        selected = self._get_selected_repositories()
        if not selected:
            title = "Info" if self._language == "en" else "提示"
            message = (
                "Please select at least one repository."
                if self._language == "en"
                else "请至少选择一个仓库。"
            )
            QMessageBox.information(self, title, message)
            return

        dirty_names = [repo.name for repo in selected if repo.is_dirty]
        if self._language == "en":
            message = (
                "This operation may take a long time. It is recommended to run when idle.\n\n"
                f"Slim {len(selected)} repository/repositories?"
            )
            if dirty_names:
                message += (
                    "\n\nThe following repositories have uncommitted changes that will be lost permanently:\n"
                    + ", ".join(dirty_names)
                )
            title = "Confirm Slim"
        else:
            message = (
                "此操作比较耗时，建议空闲时执行。\n\n"
                f"确定对 {len(selected)} 个仓库执行瘦身？"
            )
            if dirty_names:
                message += (
                    "\n\n以下仓库有未提交修改，瘦身后将永久丢失：\n"
                    + "、".join(dirty_names)
                )
            title = "确认瘦身"

        reply = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._scan_cancelled = True
        paths = [repo.path for repo in selected]
        self.slim_confirmed.emit(paths)
        self.accept()

    def apply_language(self, language: str) -> None:
        """切换对话框文案语言。"""
        self._language = language
        is_en = language == "en"
        self.setWindowTitle("Repository Slim" if is_en else "仓库瘦身")
        self.hint_label.setText(
            "Re-clone repositories via full clone + fetch + checkout (same as biu script). "
            "The project root repository is shown for reference only and cannot be slimmed."
            if is_en
            else "通过全量 clone + fetch + checkout 重新拉取仓库（与 biu 脚本一致）。"
            "工程根目录仓库仅展示占用，不支持瘦身（避免误删整个工程）。"
        )
        self.btn_select_all.setText("Select/Invert" if is_en else "全选/反选")
        self.btn_refresh_sizes.setText("Refresh Sizes" if is_en else "刷新大小")
        self.btn_cancel.setText("Cancel" if is_en else "取消")
        self.btn_slim.setText("Start Slim" if is_en else "开始瘦身")
        headers = (
            ["Select", "Repository", "Branch", "Disk Usage", "Path"]
            if is_en
            else ["选择", "仓库名", "当前分支", "磁盘占用", "路径"]
        )
        self.repo_table.setHorizontalHeaderLabels(headers)
        self._update_total_size_label()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._scan_cancelled = True
        super().closeEvent(event)
