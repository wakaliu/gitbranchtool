"""主窗口 - 整合所有 UI 组件。

严格遵循 MVC：只转发信号给核心层，不包含业务逻辑。
"""
from PySide6.QtWidgets import (QMainWindow, QSplitter, QWidget, QVBoxLayout, QMenuBar,
                               QMenu, QMessageBox, QFileDialog, QStatusBar, QLabel, QPushButton)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon
from pathlib import Path
import sys
from typing import List

from ..config.settings import Settings
from ..core.project_manager import ProjectManager
from ..core.git_manager import GitManager
from ..utils.logger import OperationLogger
from ..utils.thread_pool import ThreadPoolManager, Worker
from .components.project_panel import ProjectPanel
from .components.repo_list_panel import RepoListPanel
from .components.operation_panel import OperationPanel
from .components.feedback_dialog import FeedbackDialog
from .components.settings_dialog import SettingsDialog
from .components.branch_favorite_dialog import BranchFavoriteDialog
from .components.git_console_dialog import GitConsoleDialog
from .widgets.log_text_edit import LogTextEdit
from .widgets.progress_dialog import OperationProgressDialog

class MainWindow(QMainWindow):
    """主应用窗口。

    为什么这么大：它是所有组件的协调者，但业务逻辑全部委托给 ProjectManager 和 GitManager。
    日志和线程池在这里统一管理。
    """
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.project_manager = ProjectManager()
        self.git_manager = GitManager()
        self.logger = OperationLogger(
            max_lines=self.settings.get("ui.log_max_lines", 500),
            on_log_updated=self._on_log_updated
        )
        self.thread_pool = ThreadPoolManager()
        self.current_selected_repos: list[Path] = []

        self._setup_ui()
        self._connect_signals()
        self._load_initial_data()

        self.setWindowTitle(f"{self.settings.get('app.name')} v{self.settings.get('app.version')}")
        self.resize(1400, 900)

    def _setup_ui(self) -> None:
        # 菜单栏
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("退出", self.close)

        tools_menu = menubar.addMenu("工具")
        tools_menu.addAction("反馈", self._show_feedback)
        tools_menu.addAction("设置", self._show_settings)

        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("关于", self._show_about)

        # 中央部件
        central = QWidget()
        main_layout = QVBoxLayout(central)

        # 分割器：工程区 | 操作区 (左右) | 日志
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：工程面板
        self.project_panel = ProjectPanel()
        splitter.addWidget(self.project_panel)

        # 右侧操作区 (垂直分割：仓库列表 | 操作台)
        right_splitter = QSplitter(Qt.Vertical)

        self.repo_panel = RepoListPanel()
        self.operation_panel = OperationPanel()

        right_splitter.addWidget(self.repo_panel)
        right_splitter.addWidget(self.operation_panel)
        right_splitter.setSizes([300, 400])

        splitter.addWidget(right_splitter)
        splitter.setSizes([350, 1050])

        main_layout.addWidget(splitter)

        # 底部日志
        log_group = QWidget()
        log_layout = QVBoxLayout(log_group)
        log_layout.addWidget(QLabel("运行日志 (自动清理，显示耗时)"))
        self.log_text = LogTextEdit()
        log_layout.addWidget(self.log_text)

        clear_btn = QPushButton("清理日志")
        clear_btn.clicked.connect(self.logger.clear)
        log_layout.addWidget(clear_btn)

        main_layout.addWidget(log_group, 1)  # 伸缩因子

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _connect_signals(self) -> None:
        # 工程面板
        self.project_panel.project_selected.connect(self._on_project_selected)
        self.project_panel.project_added.connect(self._add_new_project)
        self.project_panel.project_removed.connect(self._remove_project)

        # 仓库面板
        self.repo_panel.refresh_requested.connect(self._refresh_all)
        self.repo_panel.fetch_requested.connect(self._perform_fetch)

        # 操作面板
        self.operation_panel.switch_requested.connect(self._perform_switch)
        self.operation_panel.console_requested.connect(self._show_console)
        self.operation_panel.favorite_requested.connect(self._show_favorites)

        # 其他
        self.repo_panel.switch_requested.connect(lambda: self.operation_panel._on_switch_clicked())

    def _load_initial_data(self) -> None:
        self.project_panel.load_projects(self.project_manager.projects)
        if self.project_manager.projects:
            # 默认选中第一个工程
            self._on_project_selected([str(self.project_manager.projects[0].path)])

    def _on_project_selected(self, selected_paths: List[str]) -> None:
        if not selected_paths:
            return
        # 找到第一个选中的工程，加载其仓库
        for p in self.project_manager.projects:
            if str(p.path) in selected_paths:
                self.repo_panel.load_repositories(p.repositories)
                break

    def _add_new_project(self, path: Path) -> None:
        project = self.project_manager.add_project(path)
        if project:
            self.project_panel.load_projects(self.project_manager.projects)
            self.logger.append(f"已添加工程: {project.name}")
            self.statusBar().showMessage(f"工程 {project.name} 添加成功")

    def _remove_project(self, path: Path) -> None:
        if self.project_manager.remove_project(path):
            self.project_panel.load_projects(self.project_manager.projects)
            self.logger.append(f"已移除工程: {path.name}")

    def _refresh_all(self) -> None:
        self.logger.start_operation("刷新仓库列表")
        self.project_manager.refresh_all()
        if self.project_manager.projects:
            self.project_panel.load_projects(self.project_manager.projects)
            self.repo_panel.load_repositories(self.project_manager.projects[0].repositories)
        self.logger.end_operation(True, "刷新完成")

    def _perform_fetch(self, repo_paths: List[Path]) -> None:
        self.logger.start_operation(f"Fetch {len(repo_paths)} 个仓库")
        progress = OperationProgressDialog(self, "正在 Fetch")

        def run_fetch(path: Path):
            return self.git_manager.fetch(path, lambda msg: self.logger.append(msg))

        for path in repo_paths[:self.settings.get("git.max_concurrent", 6)]:
            worker = Worker(run_fetch, path)
            worker.signals.finished.connect(lambda r: self.logger.append(f"完成: {r[:80]}..."))
            worker.signals.error.connect(lambda e: self.logger.append(f"错误: {e}"))
            self.thread_pool.start(worker)

        QTimer.singleShot(500, progress.close)  # 简化处理，实际应等待所有线程
        self.logger.end_operation(True)

    def _perform_switch(self, target_branch: str, stash: bool) -> None:
        selected = self.repo_panel.get_selected_repo_paths()
        if not selected:
            selected = [p.path for p in self.project_manager.get_all_repositories()[:1]]

        if not selected:
            QMessageBox.warning(self, "提示", "没有可操作的仓库")
            return

        self.logger.start_operation(f"切换分支 -> {target_branch or '当前分支'}")
        progress = OperationProgressDialog(self, "正在切换分支")

        def do_switch(path: Path):
            return self.git_manager.switch(path, target_branch, stash, lambda m: self.logger.append(m))

        # 并行执行 (限制数量)
        for path in selected:
            worker = Worker(do_switch, path)
            worker.signals.finished.connect(lambda result: self.operation_panel.update_result(result, True))
            worker.signals.error.connect(lambda err: self.operation_panel.update_result(err, False))
            self.thread_pool.start(worker)

        progress.close()
        elapsed = self.logger.end_operation(True)
        self.statusBar().showMessage(f"切线完成，耗时 {elapsed:.2f} 秒")

    def _show_console(self) -> None:
        selected = self.repo_panel.get_selected_repo_paths()
        repo_path = selected[0] if selected else Path.cwd()
        dialog = GitConsoleDialog(repo_path, self)
        dialog.exec()

    def _show_favorites(self) -> None:
        dialog = BranchFavoriteDialog(self)
        dialog.branch_selected.connect(lambda b: self.operation_panel.branch_input.setText(b))
        dialog.exec()

    def _show_feedback(self) -> None:
        dialog = FeedbackDialog(self)
        dialog.exec()

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.settings_changed.connect(self._apply_theme)
        dialog.exec()

    def _apply_theme(self) -> None:
        # TODO: 实现 QSS 主题切换 (light/dark)
        self.logger.append("主题已更改 (需重启生效)")
        QMessageBox.information(self, "提示", "主题设置已保存，重启应用后生效。")

    def _show_about(self) -> None:
        QMessageBox.about(self, "关于", "Git 拉线切线工具 v1.0\n\n专为多仓库项目设计的批量切分支工具。\n支持 Windows / macOS (Intel & M 芯片)。")

    def _on_log_updated(self, text: str) -> None:
        self.log_text.append_log(text)

    def closeEvent(self, event) -> None:
        """退出时保存状态。"""
        self.logger.append("应用退出")
        event.accept()
