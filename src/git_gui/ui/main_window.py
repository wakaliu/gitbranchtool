"""主窗口 - 整合所有 UI 组件。

严格遵循 MVC：只转发信号给核心层，不包含业务逻辑。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout, QMenuBar,
                               QMenu, QMessageBox, QFileDialog, QStatusBar, QLabel, QPushButton, QGroupBox)
from PySide6.QtCore import Qt, Signal, QTimer
from pathlib import Path
import sys
from typing import List
import time
import inspect
import math

from ..config.settings import Settings
from ..config.constants import APP_VERSION
from ..core.project_manager import ProjectManager
from ..core.git_manager import GitManager
from ..core.git_clone import parse_clone_progress_percent, CloneOutputThrottle
from ..utils.logger import OperationLogger, write_error_log
from ..utils.file_utils import normalize_repo_path_key, paths_refer_to_same_location, resolve_primary_repository_path
from ..utils.thread_pool import ThreadPoolManager, Worker
from ..models.project import Project
from .components.project_panel import ProjectPanel
from .components.repo_list_panel import RepoListPanel
from .components.operation_panel import OperationPanel
from .components.feedback_dialog import FeedbackDialog
from .components.settings_dialog import SettingsDialog
from .components.branch_favorite_dialog import BranchFavoriteDialog
from .components.git_console_dialog import GitConsoleDialog
from .components.clone_project_dialog import CloneProjectDialog
from .components.slim_repo_dialog import SlimRepoDialog
from ..core.update.update_controller import UpdateController
from ..ui.i18n.update_texts import get_update_texts
from .widgets.log_text_edit import LogTextEdit
from .widgets.progress_dialog import OperationProgressDialog
from .theme import build_app_stylesheet, get_icon

class MainWindow(QMainWindow):
    """主应用窗口。

    为什么这么大：它是所有组件的协调者，但业务逻辑全部委托给 ProjectManager 和 GitManager。
    日志和线程池在这里统一管理。
    """
    dispatch_to_main = Signal(object)

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.project_manager = ProjectManager()
        self.git_manager = GitManager()
        self.logger = OperationLogger(
            max_lines=self.settings.get("ui.log_max_lines", 500),
            on_log_updated=self._on_log_updated,
            on_log_refresh=self._on_log_refresh,
        )
        self.thread_pool = ThreadPoolManager()
        self.current_selected_repos: list[Path] = []
        self.current_project_path: Path | None = None
        self._active_stable_worker: Worker | None = None
        self._active_parallel_workers: list[Worker] = []
        self._parallel_op_serial: int = 0
        self._parallel_active_op_serial: int = 0
        self._parallel_progress_dialog: OperationProgressDialog | None = None
        self._inactive_project_paths: set[Path] = set()
        self._initial_repo_scan_pending: bool = False
        self._auto_refresh_busy: bool = False
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(5 * 60 * 1000)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_current_project_status)
        self._update_flow_locked = False
        self._business_operation_locked = False
        self._update_controller = UpdateController(
            self,
            self._schedule_on_main_thread,
            log_fn=self.logger.append,
            log_ephemeral_fn=self.logger.append_ephemeral,
            clear_ephemeral_logs_fn=self.logger.clear_ephemeral,
        )
        self._action_check_update = None

        self._setup_ui()
        self._connect_signals()
        self.dispatch_to_main.connect(self._execute_in_main_thread)
        self._load_initial_data()
        self._initial_repo_scan_pending = bool(self.project_manager.projects)
        if self._initial_repo_scan_pending:
            self.repo_panel.set_repositories_loading(True)
        QTimer.singleShot(0, self._restore_initial_project_selection)
        QTimer.singleShot(0, self._run_startup_project_scan)
        QTimer.singleShot(1, self._apply_settings_to_ui)
        self._auto_refresh_timer.start()
        self._update_controller.schedule_startup_check()

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
        self._action_check_update = help_menu.addAction(
            get_update_texts(self.settings.language).menu_check_updates,
            lambda: self._update_controller.run_check(auto=False),
        )
        help_menu.addAction("关于", self._show_about)

        # 中央部件
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 整体三段布局：工程区(上) / 仓库+控制台(中) / 日志区(下)
        main_splitter = QSplitter(Qt.Vertical)
        # 上：工程区域
        project_group = QGroupBox("")
        project_layout = QVBoxLayout(project_group)
        project_layout.setContentsMargins(10, 8, 10, 10)
        self.project_panel = ProjectPanel()
        project_layout.addWidget(self.project_panel)
        main_splitter.addWidget(project_group)

        # 中：仓库列表(左) + 控制台(右)
        middle_group = QGroupBox("")
        middle_widget = QWidget()
        middle_layout = QHBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(10)

        self.repo_panel = RepoListPanel()
        self.operation_panel = OperationPanel()

        self.middle_splitter = QSplitter(Qt.Horizontal)
        self.middle_splitter.addWidget(self.repo_panel)
        self.middle_splitter.addWidget(self.operation_panel)
        self.middle_splitter.setChildrenCollapsible(False)
        self.middle_splitter.setSizes([900, 500])
        middle_layout.addWidget(self.middle_splitter)
        middle_group_layout = QVBoxLayout(middle_group)
        middle_group_layout.setContentsMargins(10, 8, 10, 10)
        middle_group_layout.addWidget(middle_widget)
        main_splitter.addWidget(middle_group)

        # 底部日志
        log_wrapper_group = QGroupBox("")
        log_wrapper_layout = QVBoxLayout(log_wrapper_group)
        log_wrapper_layout.setContentsMargins(10, 8, 10, 10)
        log_group = QWidget()
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        log_header = QHBoxLayout()
        log_header.setSpacing(8)
        self.log_title_label = QLabel("运行日志 (自动清理，显示耗时)")
        self.log_title_label.setProperty("role", "section-title")
        log_header.addWidget(self.log_title_label, 1)
        self.clear_log_btn = QPushButton()
        self.clear_log_btn.setProperty("role", "compact")
        self.clear_log_btn.setIcon(get_icon(self, "clear"))
        self.clear_log_btn.setFixedHeight(24)
        self.clear_log_btn.setToolTip("清理日志")
        self.clear_log_btn.clicked.connect(self.logger.clear)
        log_header.addWidget(self.clear_log_btn)
        log_layout.addLayout(log_header)
        self.log_text = LogTextEdit()
        log_layout.addWidget(self.log_text, 1)

        log_wrapper_layout.addWidget(log_group)
        main_splitter.addWidget(log_wrapper_group)
        main_splitter.setSizes([240, 520, 140])
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 6)
        main_splitter.setStretchFactor(2, 1)
        main_layout.addWidget(main_splitter)

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _connect_signals(self) -> None:
        # 工程面板
        self.project_panel.project_selected.connect(self._on_project_selected)
        self.project_panel.project_added.connect(self._add_new_project)
        self.project_panel.project_removed.connect(self._remove_project)
        self.project_panel.clone_requested.connect(self._show_clone_dialog)

        # 仓库面板
        self.repo_panel.refresh_requested.connect(self._refresh_all)
        self.repo_panel.fetch_requested.connect(self._perform_fetch)
        self.repo_panel.order_changed.connect(self._on_repo_order_changed)
        self.repo_panel.slim_requested.connect(self._show_slim_dialog)

        # 操作面板
        self.operation_panel.switch_requested.connect(self._perform_switch)
        self.operation_panel.fill_requested.connect(self._fill_target_branch_from_selected_repo)
        self.operation_panel.console_requested.connect(self._show_console)
        self.operation_panel.favorite_requested.connect(self._show_favorites)

        # 其他
        self.repo_panel.switch_requested.connect(lambda: self.operation_panel._on_switch_clicked())

    def _load_initial_data(self) -> None:
        self.project_panel.load_projects(self.project_manager.projects)

    def _run_startup_project_scan(self) -> None:
        """首帧后再于后台扫描各工程内 Git 仓库，避免阻塞事件循环导致窗口白屏过久。"""
        paths = [p.path for p in list(self.project_manager.projects)]
        if not paths:
            self._initial_repo_scan_pending = False
            self.repo_panel.set_repositories_loading(False)
            return

        def scan_initial() -> None:
            self.project_manager.scan_projects_for_paths(paths)

        worker = Worker(scan_initial)
        worker.signals.finished.connect(self._on_startup_project_scan_finished)
        worker.signals.error.connect(
            lambda err: self.dispatch_to_main.emit(
                lambda e=err: self._on_startup_project_scan_failed(e)
            )
        )
        self.thread_pool.start(worker)

    def _on_startup_project_scan_finished(self, _result: object) -> None:
        """后台扫描完成后在主线程刷新工程列表与当前工程下的仓库表。"""
        self._initial_repo_scan_pending = False
        self.repo_panel.set_repositories_loading(False)
        saved = self.current_project_path
        self.project_panel.load_projects(self.project_manager.projects)
        if saved and self.project_panel.select_project_by_path(saved):
            self._on_project_selected([str(saved)])
        elif self.project_manager.projects:
            self.project_panel.select_first_project()
            self._on_project_selected([str(self.project_manager.projects[0].path)])

    def _on_startup_project_scan_failed(self, err: str) -> None:
        """启动扫描失败时仍需结束加载态，避免界面永久停在「加载中」。"""
        self._initial_repo_scan_pending = False
        self.repo_panel.set_repositories_loading(False)
        self.logger.append(f"启动扫描工程失败: {err}")
        if self.current_project_path:
            for p in self.project_manager.projects:
                if p.path == self.current_project_path:
                    self.repo_panel.load_repositories(p.repositories)
                    break

    def _restore_initial_project_selection(self) -> None:
        """窗口显示后恢复默认工程选中，避免初始化阶段选中状态丢失。"""
        if not self.project_manager.projects:
            return
        # 优先恢复上次选中的工程，不存在则回退到第一个
        last_selected = self.settings.get_last_selected_project()
        if last_selected and self.project_panel.select_project_by_path(last_selected):
            self._on_project_selected([str(last_selected)])
            return
        self.project_panel.select_first_project()
        self._on_project_selected([str(self.project_manager.projects[0].path)])

    def _on_project_selected(self, selected_paths: List[str]) -> None:
        if not selected_paths:
            return
        self.current_project_path = Path(selected_paths[0])
        self.settings.save_last_selected_project(selected_paths[0])
        # 找到第一个选中的工程，加载其仓库
        for p in self.project_manager.projects:
            if str(p.path) in selected_paths:
                if self._initial_repo_scan_pending and not p.repositories:
                    self.repo_panel.set_repositories_loading(True)
                else:
                    self.repo_panel.load_repositories(p.repositories)
                break
        self._update_workspace_header()

    def _on_repo_order_changed(self, ordered_repo_paths: List[str]) -> None:
        """仓库拖拽重排后，持久化顺序。"""
        if not self.current_project_path:
            return
        paths = [Path(p) for p in ordered_repo_paths]
        self.project_manager.update_repo_order(self.current_project_path, paths)

    def _add_new_project(self, path: Path) -> None:
        """使用 Worker 在后台线程中执行耗时的扫描操作，避免界面卡住。"""
        self.logger.start_operation(f"添加工程: {path.name if hasattr(path, 'name') else str(path)}")

        def scan_and_add():
            project = self.project_manager.add_project(path)
            return project

        worker = Worker(scan_and_add)
        worker.signals.finished.connect(self._on_project_added_finished)
        worker.signals.error.connect(
            lambda e: self.dispatch_to_main.emit(
                lambda: self.logger.append(f"添加工程失败: {e}")
            )
        )
        self.thread_pool.start(worker)

    def _on_project_added_finished(self, project: Project) -> None:
        """后台扫描完成后更新 UI（必须在主线程）。"""
        if project:
            self.project_panel.load_projects(self.project_manager.projects)
            if not self.project_panel.select_project_by_path(project.path):
                self._on_project_selected([str(project.path)])
            self.logger.end_operation(True, f"已添加工程: {project.name}")
            self.statusBar().showMessage(f"工程 {project.name} 添加成功")
        else:
            self.logger.end_operation(False, "添加失败或已存在")

    def _remove_project(self, path: Path) -> None:
        if not self.project_manager.remove_project(path):
            return
        was_current = self.current_project_path == path
        self._inactive_project_paths.discard(path)
        self.project_panel.load_projects(self.project_manager.projects)
        self.logger.append(f"已移除工程: {path.name}")

        if not was_current:
            self._update_workspace_header()
            return

        if self.project_manager.projects:
            self.project_panel.select_first_project()
            return

        self.current_project_path = None
        self.settings.save_last_selected_project("")
        self.repo_panel.load_repositories([])
        self._update_workspace_header()

    def _show_clone_dialog(self) -> None:
        """弹出克隆工程对话框并执行克隆。"""
        dialog = CloneProjectDialog(self, default_target_dir=self._default_clone_target_dir())
        dialog.primary_project_ready.connect(
            self._add_new_project,
            Qt.ConnectionType.QueuedConnection,
        )
        dialog.exec()

    def _default_clone_target_dir(self) -> Path:
        """克隆默认目录：首个工程上级目录，否则下载目录。"""
        if self.project_manager.projects:
            first_project = self.project_manager.projects[0].path
            parent = first_project.parent
            if parent.exists():
                return parent
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            return downloads
        return Path.home()

    def _refresh_all(self) -> None:
        self.logger.start_operation("刷新仓库列表")
        if not self.current_project_path:
            self.logger.end_operation(False, "未选择工程")
            return
        count, removed = self.project_manager.rescan_project(self.current_project_path)
        project = self.project_manager.get_project_by_path(self.current_project_path)
        if project:
            self.repo_panel.load_repositories(project.repositories)
        self._inactive_project_paths.discard(self.current_project_path)
        msg = f"刷新完成：{count} 个仓库"
        if removed > 0:
            msg += f"，已移除 {removed} 个无效路径"
        self.logger.end_operation(True, msg)
        self._update_workspace_header()

    def _show_slim_dialog(self) -> None:
        """打开仓库瘦身选择弹窗。"""
        if self._is_git_operation_running():
            QMessageBox.warning(self, "提示", "当前有 Git 操作进行中，请稍后再试。")
            return
        if not self.current_project_path:
            QMessageBox.warning(self, "提示", "请先选择一个工程。")
            return
        project = self.project_manager.get_project_by_path(self.current_project_path)
        if not project or not project.repositories:
            QMessageBox.warning(self, "提示", "当前工程暂无仓库，请先刷新或重新添加工程。")
            return
        dialog = SlimRepoDialog(
            self,
            repositories=project.repositories,
            project_root=project.path,
        )
        dialog.slim_confirmed.connect(self._perform_slim)
        dialog.exec()

    def _perform_slim(self, repo_paths: List[Path]) -> None:
        """对选中仓库执行 re-clone 瘦身（仅保留当前分支）。"""
        if not repo_paths:
            return
        if self.current_project_path:
            project_root = self.current_project_path
            project = self.project_manager.get_project_by_path(project_root)
            primary_path = resolve_primary_repository_path(
                project_root,
                project.repositories if project else [],
            )
            repo_paths = [
                p for p in repo_paths
                if not (
                    paths_refer_to_same_location(p, project_root)
                    or (
                        primary_path is not None
                        and paths_refer_to_same_location(p, primary_path)
                    )
                )
            ]
        if not repo_paths:
            QMessageBox.warning(self, "提示", "工程根目录不支持瘦身，请仅选择子仓库。")
            return
        self._set_business_ui_locked(True)
        paths = list(repo_paths)

        def unlock_and_refresh() -> None:
            self._set_business_ui_locked(False)
            try:
                self.project_manager.refresh_sync_state_for_paths(paths)
                if self.current_project_path:
                    for proj in self.project_manager.projects:
                        if proj.path == self.current_project_path:
                            self.repo_panel.load_repositories(proj.repositories)
                            break
            except Exception as e:
                write_error_log("瘦身后刷新同步列", str(e))

        self._run_parallel_git_operation(
            operation_name="瘦身",
            repo_paths=paths,
            per_repo_fn=self._slim_single_repo,
            write_result_to_panel=True,
            force_stable_serial=True,
            enable_step_logs=True,
            progress_hint="瘦身进行中，详情见下方运行日志。",
            finally_callback=unlock_and_refresh,
        )

    def _slim_single_repo(self, path: Path, on_step=None, cancel_check=None) -> str:
        """执行单个仓库瘦身，并通过 on_step 回传步骤日志。"""

        def relay(message: str) -> None:
            if on_step:
                on_step(message)

        return self.git_manager.slim_repo(path, callback=relay, cancel_check=cancel_check)

    @staticmethod
    def _format_eta_seconds(seconds: int) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds} 秒"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes} 分 {sec} 秒"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} 小时 {minutes} 分"

    def _handle_step_log_progress(
        self,
        progress: OperationProgressDialog,
        total: int,
        index: int,
        path: Path,
        state: dict,
        message: str,
        *,
        update_log: bool = True,
        update_progress: bool = True,
    ) -> None:
        """瘦身/长任务步骤日志与细粒度进度、预计剩余时间。"""
        if state.get("cancelled") or state.get("done"):
            return
        now = time.time()
        repo_start = state.get("repo_start", now)
        elapsed_repo = max(0.0, now - repo_start)
        durations: list[float] = state.setdefault("repo_durations", [])
        avg = sum(durations) / len(durations) if durations else max(elapsed_repo, 120.0)
        clone_map: dict[int, float] = state.setdefault("clone_percent_by_index", {})

        parsed_pct = parse_clone_progress_percent(message)
        if parsed_pct is not None:
            clone_map[index] = parsed_pct / 100.0

        is_heartbeat = (
            "clone 进行中" in message
            or "切线进行中" in message
            or "fetch 进行中" in message
        )
        if update_log and (parsed_pct is not None or not is_heartbeat):
            self.logger.append(f"[{path.name}] {message}")
        elif update_log and is_heartbeat:
            self.logger.append(f"[{path.name}] {message}")

        if not update_progress:
            return

        if index in clone_map and clone_map[index] > 0:
            sub_fraction = clone_map[index]
        elif is_heartbeat or "执行 clone" in message or "正在 checkout" in message:
            # 无 git 百分比输出时用渐近曲线，避免长期停在 0%
            sub_fraction = 1.0 - math.exp(-elapsed_repo / max(avg * 2.0, 300.0))
            sub_fraction = min(0.99, sub_fraction)
        else:
            sub_fraction = min(0.15, elapsed_repo / max(avg, 30.0) * 0.15)

        overall_fraction = ((index - 1) + sub_fraction) / max(total, 1)
        repo_estimate = max(avg, elapsed_repo * 1.05)
        current_left = max(0.0, repo_estimate - elapsed_repo)
        remaining_repos = max(0, total - index)
        eta_seconds = int(current_left + avg * remaining_repos)
        eta_text = self._format_eta_seconds(eta_seconds)
        elapsed_text = self._format_eta_seconds(int(elapsed_repo))
        status = (
            f"{index}/{total} - {path.name} | 已用时 {elapsed_text} | 预计剩余约 {eta_text}"
        )
        if parsed_pct is not None:
            status += f" | clone {parsed_pct}%"
        elif is_heartbeat:
            if "fetch 进行中" in message:
                status += " | fetch 进行中"
            elif "切线进行中" in message:
                status += " | checkout 进行中"
            else:
                status += " | clone 进行中"
        try:
            progress.update_progress_fraction(overall_fraction, status)
        except RuntimeError:
            pass

    def _perform_fetch(self, repo_paths: List[Path]) -> None:
        self._run_parallel_git_operation(
            operation_name="Fetch",
            repo_paths=repo_paths,
            # 重要：后台线程不能直接触发 UI 日志更新，避免 Qt 跨线程闪退
            per_repo_fn=lambda path: self.git_manager.fetch(path),
        )

    def _fill_target_branch_from_selected_repo(self) -> None:
        """将目标分支填入为“当前第一个选中仓库”的分支。"""
        selected_paths = self.repo_panel.get_selected_repo_paths()
        if not selected_paths:
            QMessageBox.information(self, "提示", "请先勾选一个仓库")
            return
        first_selected_path = selected_paths[0]
        for repo in self.repo_panel.repositories:
            if repo.path == first_selected_path:
                self.operation_panel.set_target_branch(repo.current_branch or "HEAD")
                return
        QMessageBox.warning(self, "提示", "未找到选中仓库的分支信息，请先刷新仓库列表")

    def _is_git_operation_running(self) -> bool:
        """避免自动刷新与手动 Git 操作并发导致状态抖动。"""
        return bool(self._active_stable_worker or self._active_parallel_workers)

    def _invalidate_parallel_workers(self) -> None:
        """使在途并行任务回调失效，并终止可能仍在运行的 git 子进程。

        取消后若旧 Worker 仍占线程池且回调仍挂到上一轮 state，再次 Fetch 会长期停在 0%。
        """
        self._parallel_op_serial += 1
        self._active_parallel_workers.clear()
        self._kill_git_processes()

    def _release_parallel_progress_dialog(self, dlg: OperationProgressDialog | None) -> None:
        """安全释放并行操作进度框，避免 cancel 延迟回调误关新一轮对话框导致闪退。"""
        if dlg is None:
            return
        try:
            dlg.blockSignals(True)
        except Exception:
            pass
        try:
            dlg.canceled.disconnect()
        except Exception:
            pass
        try:
            dlg.hide()
        except Exception:
            pass
        try:
            dlg.close()
        except Exception:
            pass
        try:
            dlg.deleteLater()
        except Exception:
            pass
        if self._parallel_progress_dialog is dlg:
            self._parallel_progress_dialog = None

    def _auto_refresh_current_project_status(self) -> None:
        """每 5 分钟自动刷新当前工程仓库状态，跳过不活跃工程。

        定时器槽必须在主线程立即返回：禁止在此调用 subprocess（fork），否则在 Qt 多线程
        与休眠唤醒后易触发 malloc/atfork 相关 SIGSEGV（见崩溃栈 _posixsubprocess + fork）。
        不活跃判断、剔除失效路径、git 状态采集均在 Worker 中完成。
        """
        if not self.current_project_path:
            return
        if self._update_flow_locked or self._business_operation_locked:
            return
        if self._is_git_operation_running():
            return
        if self._auto_refresh_busy:
            return
        current_path = self.current_project_path
        self._auto_refresh_busy = True

        def run_auto_refresh() -> tuple[str, Path, int, list[tuple[Path, str, str, int, int]]]:
            pm = self.project_manager
            project = pm.get_project_by_path(current_path)
            if not project:
                return ("missing", current_path, 0, [])
            if pm.is_project_inactive(current_path, stale_days=7):
                return ("inactive", current_path, 0, [])
            removed = pm.prune_invalid_repositories(project)
            if not project.repositories:
                return ("empty", current_path, removed, [])
            from ..utils.file_utils import get_current_branch, get_sync_status

            rows: list[tuple[Path, str, str, int, int]] = []
            for rp in list(project.repositories):
                branch = get_current_branch(rp)
                status, ahead_count, behind_count = get_sync_status(rp)
                rows.append((rp, branch, status, ahead_count, behind_count))
            return ("ok", current_path, removed, rows)

        worker = Worker(run_auto_refresh)
        worker.setAutoDelete(True)
        worker.signals.finished.connect(self._on_auto_refresh_worker_finished)
        worker.signals.error.connect(self._on_auto_refresh_worker_failed)
        self.thread_pool.start(worker)

    def _on_auto_refresh_worker_finished(self, payload: object) -> None:
        """自动刷新 git 采集完成，在主线程合并到模型并刷新表格。"""
        self._auto_refresh_busy = False
        if self._update_flow_locked:
            return
        if not isinstance(payload, tuple) or len(payload) != 4:
            return
        kind, path, removed, rows = payload
        if path != self.current_project_path:
            return
        if kind == "missing":
            return
        if kind == "inactive":
            if path not in self._inactive_project_paths:
                self._inactive_project_paths.add(path)
                self.logger.append(f"{path.name} 已标记为不活跃工程，自动刷新暂停。")
            return
        self._inactive_project_paths.discard(path)
        project = self.project_manager.get_project_by_path(path)
        if not project:
            return
        if kind == "empty":
            self.repo_panel.load_repositories(project.repositories)
            if removed > 0:
                self.statusBar().showMessage(f"自动刷新：已移除 {removed} 个无效仓库")
            return
        if kind != "ok":
            return
        by_path: dict[str, tuple[Path, str, str, int, int]] = {}
        for row in rows:
            rp, branch, status, ahead_count, behind_count = row
            by_path[str(rp)] = row
        still_valid = [
            r
            for r in project.repositories
            if r.path.exists() and str(r.path) in by_path
        ]
        extra_removed = len(project.repositories) - len(still_valid)
        if extra_removed > 0:
            project.repositories = still_valid
            self.project_manager.settings.save_repo_order(
                str(project.path),
                [str(r.path) for r in project.repositories],
            )
        removed += extra_removed
        refreshed = 0
        for repo in project.repositories:
            row = by_path.get(str(repo.path))
            if not row:
                continue
            _, branch, status, ahead_count, behind_count = row
            repo.current_branch = branch
            repo.status = status
            repo.ahead_count = ahead_count
            repo.behind_count = behind_count
            refreshed += 1
        self.repo_panel.load_repositories(project.repositories)
        if refreshed > 0 or removed > 0:
            msg = f"自动刷新完成：{refreshed} 个仓库"
            if removed > 0:
                msg += f"，已移除 {removed} 个无效路径"
            self.statusBar().showMessage(msg)

    def _on_auto_refresh_worker_failed(self, err: str) -> None:
        self._auto_refresh_busy = False
        if self._update_flow_locked:
            return
        write_error_log("自动刷新后台失败", err[:2000] if err else "")

    def _perform_switch(self, target_branch: str, stash: bool) -> None:
        """执行一键切线操作。

        使用稳定串行模式（单个Worker顺序执行所有仓库），避免并行Qt回调导致的卡住/闪退。
        按钮状态通过 OperationPanel.reset_switch_button() 在主线程收尾时同步重置，确保可再次点击。
        """
        write_error_log("切线入口", f"target_branch={target_branch!r}, stash={stash}")
        selected = self.repo_panel.get_selected_repo_paths()
        write_error_log("切线入口", f"selected_count={len(selected)}")
        if not selected:
            selected = [p.path for p in self.project_manager.get_all_repositories()[:1]]
            write_error_log("切线入口", f"fallback_selected_count={len(selected)}")

        if not selected:
            write_error_log("切线入口", "没有可操作仓库，直接返回")
            QMessageBox.warning(self, "提示", "没有可操作的仓库")
            return

        action_name = f"切换分支 -> {target_branch or '当前分支'}"
        write_error_log("切线入口", f"开始稳定串行操作: {action_name}, repos={len(selected)} (避免并行Qt回调闪退/卡住)")

        def switch_repo(path: Path, on_step=None, cancel_check=None) -> str:
            def relay(message: str) -> None:
                if on_step:
                    on_step(message)

            return self.git_manager.switch(path, target_branch, stash, callback=relay)

        self._run_parallel_git_operation(
            operation_name=action_name,
            repo_paths=selected,
            per_repo_fn=switch_repo,
            write_result_to_panel=True,
            force_stable_serial=True,
            enable_step_logs=True,
            progress_hint="切线进行中，大仓 checkout 可能需数分钟；详情见下方运行日志。",
        )

    def _run_parallel_git_operation(
        self,
        operation_name: str,
        repo_paths: List[Path],
        per_repo_fn,
        write_result_to_panel: bool = False,
        finally_callback=None,
        progress_hint: str | None = None,
        force_stable_serial: bool = False,
        enable_step_logs: bool = False,
    ) -> None:
        """统一执行 Git 操作。

        如果 write_result_to_panel=True (一键切线)，使用稳定串行模式 (单个Worker顺序执行，UI更新安全，避免卡住/闪退)。
        否则使用并行 (如Fetch)。按钮状态在所有路径都通过 reset_switch_button 确保重置。
        """
        if not repo_paths:
            return
        self.operation_panel.clear_result()

        if write_result_to_panel and force_stable_serial:
            self._run_switch_operation_stable(
                operation_name,
                repo_paths,
                per_repo_fn,
                finally_callback=finally_callback,
                progress_hint=progress_hint,
                enable_step_logs=enable_step_logs,
            )
            return

        def invoke_finally() -> None:
            if finally_callback:
                try:
                    finally_callback()
                except Exception as e:
                    write_error_log("操作收尾回调异常", str(e))

        total = len(repo_paths)
        self._parallel_op_serial += 1
        op_serial = self._parallel_op_serial
        self._parallel_active_op_serial = op_serial
        if self._active_parallel_workers:
            self._kill_git_processes()
        self._release_parallel_progress_dialog(self._parallel_progress_dialog)
        state = {
            "completed": 0,
            "success": 0,
            "failed": 0,
            "results": [],
            "cancelled": False,
            "finalized": False,
            "progress_closed": False,
            "op_serial": op_serial,
        }
        self._active_parallel_workers = []

        self.logger.clear()
        self.logger.start_operation(f"{operation_name} ({total} 个仓库)")
        progress = OperationProgressDialog(self, f"正在执行: {operation_name}")
        self._parallel_progress_dialog = progress
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.update_progress(0, total, f"准备开始，目标仓库: {total}")
        progress.open()
        self.operation_panel.btn_switch.setEnabled(False)

        def safe_close_parallel_progress() -> None:
            if state.get("progress_closed"):
                return
            state["progress_closed"] = True
            if self._parallel_progress_dialog is progress:
                self._release_parallel_progress_dialog(progress)

        def _update_parallel_progress(completed: int, message: str) -> None:
            if state.get("progress_closed") or state["cancelled"] or state["finalized"]:
                return
            if self._parallel_progress_dialog is not progress:
                return
            try:
                progress.update_progress(completed, total, message)
            except RuntimeError:
                pass

        def finalize() -> None:
            if state["finalized"]:
                return
            state["finalized"] = True
            try:
                write_error_log(
                    "并行操作 finalize",
                    f"{operation_name} completed={state['completed']} success={state['success']} failed={state['failed']} total={total}",
                )
                elapsed = self.logger.end_operation(state["failed"] == 0)
                summary = (
                    f"{operation_name} 完成：成功 {state['success']}，失败 {state['failed']}，"
                    f"总计 {total}，耗时 {elapsed:.2f} 秒"
                )
                self.logger.append(summary)
                self.statusBar().showMessage(summary)
                if write_result_to_panel:
                    self.operation_panel.update_result(summary, state["failed"] == 0)
                safe_close_parallel_progress()
                self.operation_panel.reset_switch_button()
                self._active_parallel_workers.clear()
                invoke_finally()
            except Exception as e:
                write_error_log("finalize 异常", f"{operation_name}: {e}")
                try:
                    safe_close_parallel_progress()
                    self.operation_panel.reset_switch_button()
                    self._active_parallel_workers.clear()
                    invoke_finally()
                except Exception:
                    pass

        def _is_stale_parallel_callback() -> bool:
            return state["op_serial"] != self._parallel_op_serial

        def on_finished(path: Path, output: str) -> None:
            if _is_stale_parallel_callback() or state["cancelled"] or state["finalized"]:
                return
            state["completed"] += 1
            try:
                write_error_log("并行操作 on_finished", f"{operation_name} repo={path}")
                state["success"] += 1
                message = f"[{path.name}] 成功"
                self.logger.append(message)
                state["results"].append((str(path), True, output))
                _update_parallel_progress(
                    state["completed"],
                    f"{state['completed']}/{total} - {path.name}",
                )
                # 只在 finalize 时更新 result_panel 为汇总信息 (避免并行时频繁闪烁)
                if state["completed"] >= total:
                    finalize()
            except Exception as e:
                write_error_log("on_finished 回调异常", f"{path}\n{e}")
                state["failed"] += 1
                if state["completed"] >= total:
                    finalize()

        def on_error(path: Path, err: str) -> None:
            if _is_stale_parallel_callback() or state["cancelled"] or state["finalized"]:
                return
            state["completed"] += 1
            try:
                write_error_log("并行操作 on_error", f"{operation_name} repo={path}\n{err[:400] if err else ''}")
                state["failed"] += 1
                self.logger.append(f"[{path.name}] 失败: {err.splitlines()[0] if err else '未知错误'}")
                state["results"].append((str(path), False, err))
                _update_parallel_progress(
                    state["completed"],
                    f"{state['completed']}/{total} - {path.name} (失败)",
                )
                # 只在 finalize 时更新 result_panel 为汇总信息 (避免并行时频繁闪烁)
                if state["completed"] >= total:
                    finalize()
            except Exception as e:
                write_error_log("on_error 回调异常", f"{path}\n{e}")
                if state["completed"] >= total:
                    finalize()

        def on_cancel() -> None:
            """用户点击取消：先终止 git；UI 收尾推迟到下一事件循环，避免 canceled 栈内关窗闪退。"""
            if state["finalized"] or state.get("progress_closed"):
                return
            if self._parallel_progress_dialog is not progress:
                return
            state["cancelled"] = True
            state["finalized"] = True
            self._parallel_op_serial += 1
            self._active_parallel_workers.clear()
            self._kill_git_processes()
            captured_op_serial = op_serial

            def finish_cancel_ui() -> None:
                if self._parallel_active_op_serial != captured_op_serial:
                    self.operation_panel.reset_switch_button()
                    return
                if state.get("progress_closed"):
                    self.operation_panel.reset_switch_button()
                    return
                if self._parallel_progress_dialog is not progress:
                    self.operation_panel.reset_switch_button()
                    return
                try:
                    self.logger.append("用户取消操作，正在终止 git 进程...")
                    self.logger.end_operation(False, "用户已取消")
                except Exception:
                    pass
                safe_close_parallel_progress()
                self.operation_panel.reset_switch_button()
                invoke_finally()

            QTimer.singleShot(0, finish_cancel_ui)

        progress.canceled.connect(on_cancel)

        for path in repo_paths:
            # 通过线程池限制并发，避免高负载卡顿
            worker = Worker(lambda p=path: per_repo_fn(p))
            worker.signals.finished.connect(
                lambda output, p=path: self.dispatch_to_main.emit(
                    lambda: on_finished(p, output)
                )
            )
            worker.signals.error.connect(
                lambda err, p=path: self.dispatch_to_main.emit(
                    lambda: on_error(p, err)
                )
            )
            self._active_parallel_workers.append(worker)
            self.thread_pool.start(worker)

    def _run_switch_operation_stable(
        self,
        operation_name: str,
        repo_paths: List[Path],
        per_repo_fn,
        finally_callback=None,
        progress_hint: str | None = None,
        enable_step_logs: bool = False,
    ) -> None:
        """一键切线稳定串行模式：单个后台Worker顺序执行所有仓库，主线程统一更新UI。

        这避免了并行时多个Worker同时回调导致的Qt事件风暴、33%卡住或闪退。
        每个仓库仍会显示进度和日志，适合长时间git操作。
        """
        total = len(repo_paths)
        state = {"done": False, "cancelled": False, "progress_closed": False, "repo_durations": []}
        accepts_step = enable_step_logs and len(inspect.signature(per_repo_fn).parameters) >= 2
        self.logger.clear()
        self.logger.start_operation(f"{operation_name} ({total} 个仓库)")
        progress = OperationProgressDialog(self, f"正在执行: {operation_name}")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.update_progress(0, total, f"准备开始，目标仓库: {total}")
        progress.open()
        self.operation_panel.btn_switch.setEnabled(False)
        hint = progress_hint or f"{operation_name}进行中，汇总结果将在完成后显示在此处；详情见下方运行日志。"
        self.operation_panel.update_result(hint, True)
        write_error_log("稳定串行模式", f"启用稳定串行模式: op={operation_name} repos={total}")

        def safe_close_progress(*, rejected: bool = False) -> None:
            if state.get("progress_closed"):
                return
            state["progress_closed"] = True
            try:
                progress.blockSignals(True)
            except Exception:
                pass
            try:
                progress.reset()
            except Exception:
                pass
            try:
                if rejected:
                    progress.reject()
                else:
                    progress.accept()
            except Exception:
                pass
            try:
                progress.hide()
            except Exception:
                pass
            try:
                progress.close()
            except Exception:
                pass
            try:
                progress.deleteLater()
            except Exception:
                pass

        def invoke_finally() -> None:
            if finally_callback:
                try:
                    finally_callback()
                except Exception as e:
                    write_error_log("操作收尾回调异常", str(e))

        def on_stable_cancel() -> None:
            state["cancelled"] = True
            self._kill_git_processes()
            self.logger.append(f"用户取消{operation_name}，正在终止 git 进程…")
            safe_close_progress(rejected=True)
            self.operation_panel.reset_switch_button()
            invoke_finally()

        progress.canceled.connect(on_stable_cancel)

        def emit_progress(index: int, path: Path, ok: bool, text: str) -> None:
            if state["done"]:
                return
            if enable_step_logs:
                progress.update_progress_fraction(
                    index / max(total, 1),
                    f"{index}/{total} - {path.name} 完成",
                )
            else:
                progress.update_progress(index, total, f"{index}/{total} - {path.name}")
            preview = "操作完成"
            if text and text.strip():
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped:
                        preview = stripped
                        break
            if len(preview) > 90:
                preview = preview[:90] + "..."
            self.operation_panel.update_result(
                f"[{index}/{total}] {path.name} - {'成功' if ok else '失败'}：{preview}",
                ok,
            )
            if ok:
                self.logger.append(f"--- [{path.name}] {operation_name}成功 ---")
            else:
                self.logger.append(f"--- [{path.name}] {operation_name}失败 ---")
            if text and text.strip():
                for line in text.strip().splitlines():
                    stripped = line.strip()
                    if stripped:
                        self.logger.append(f"  {stripped}")
            elif not ok:
                self.logger.append(f"  {text.splitlines()[0] if text else '未知错误'}")

        def on_done(results):
            try:
                state["done"] = True
                success = sum(1 for _, ok, _, _ in results if ok)
                failed = len(results) - success
                was_cancelled = state.get("cancelled", False)
                op_ok = failed == 0 and not was_cancelled
                elapsed = self.logger.end_operation(op_ok)
                if was_cancelled:
                    summary = (
                        f"{operation_name} 已取消：已完成 {success}，失败 {failed}，"
                        f"总计 {total}，耗时 {elapsed:.2f} 秒"
                    )
                else:
                    summary = (
                        f"{operation_name} 完成：成功 {success}，失败 {failed}，"
                        f"总计 {total}，耗时 {elapsed:.2f} 秒"
                    )
                self.logger.append(f"【汇总】{summary}")
                self.statusBar().showMessage(summary)
                self.operation_panel.update_result(summary, op_ok)
                if not was_cancelled and repo_paths:
                    try:
                        self.project_manager.refresh_sync_state_for_paths(repo_paths)
                        if self.current_project_path:
                            for proj in self.project_manager.projects:
                                if proj.path == self.current_project_path:
                                    self.repo_panel.load_repositories(proj.repositories)
                                    break
                    except Exception as e:
                        write_error_log("切线后刷新同步列", str(e))
            finally:
                self._active_stable_worker = None
                safe_close_progress()
                self.operation_panel.reset_switch_button()
                invoke_finally()

        def on_fail(err):
            err_head = err.splitlines()[0] if err else "未知错误"
            self.logger.append(f"批处理异常: {err_head}")
            if err and len(err) > len(err_head):
                for line in err.splitlines()[1:12]:
                    if line.strip():
                        self.logger.append(f"  {line.strip()}")
            self.logger.end_operation(False)
            self.operation_panel.update_result(f"{operation_name}执行异常：{err_head}", False)
            self._active_stable_worker = None
            safe_close_progress()
            self.operation_panel.reset_switch_button()
            invoke_finally()

        def run_all_with_cancel_check():
            """包装run_all，支持在循环中检查取消状态并提前退出。"""
            results = []
            for index, path in enumerate(repo_paths, start=1):
                if state.get("cancelled", False):
                    self.dispatch_to_main.emit(
                        lambda: self.logger.append("操作已取消，停止剩余仓库处理。")
                    )
                    break
                try:
                    state["repo_start"] = time.time()
                    state.setdefault("clone_percent_by_index", {}).pop(index, None)
                    throttles: dict[int, CloneOutputThrottle] = state.setdefault("clone_throttles", {})
                    throttles.pop(index, None)
                    self.git_manager._unlock_git(path)

                    def make_step_cb(p=path, i=index):
                        def step_cb(msg: str) -> None:
                            if not accepts_step:
                                return
                            if state.get("cancelled"):
                                return
                            is_heartbeat = (
                                "clone 进行中" in msg
                                or "切线进行中" in msg
                                or "fetch 进行中" in msg
                            )
                            is_git_line = msg.startswith("  ")
                            if is_git_line or is_heartbeat:
                                throttle = throttles.setdefault(i, CloneOutputThrottle())
                                if is_heartbeat:
                                    should_log, should_progress = throttle.on_heartbeat()
                                else:
                                    should_log, should_progress = throttle.on_git_line(msg.strip())
                                if not should_log and not should_progress:
                                    return
                            else:
                                should_log = True
                                should_progress = True
                            self.dispatch_to_main.emit(
                                lambda m=msg, rp=p, idx=i, sl=should_log, sp=should_progress: self._handle_step_log_progress(
                                    progress, total, idx, rp, state, m,
                                    update_log=sl, update_progress=sp,
                                )
                            )
                        return step_cb

                    if accepts_step:
                        cancel_fn = lambda: state.get("cancelled", False)
                        if len(inspect.signature(per_repo_fn).parameters) >= 3:
                            output = per_repo_fn(path, make_step_cb(), cancel_fn)
                        else:
                            output = per_repo_fn(path, make_step_cb())
                    else:
                        output = per_repo_fn(path)
                    state["repo_durations"].append(time.time() - state["repo_start"])
                    results.append((path, True, output, index))
                    self.dispatch_to_main.emit(
                        lambda i=index, p=path, t=output: emit_progress(i, p, True, t)
                    )
                except Exception as e:
                    err_text = str(e)
                    results.append((path, False, err_text, index))
                    self.dispatch_to_main.emit(
                        lambda i=index, p=path, t=err_text: emit_progress(i, p, False, t)
                    )
            return results

        def queue_switch_done(results):
            """Worker 的 finished 可能在工作线程触发；必须通过 dispatch_to_main 在主线程执行 on_done，
            否则 QProgressDialog 的 accept/close 无效，弹窗会卡在 100%。"""
            self.dispatch_to_main.emit(lambda r=results: on_done(r))

        def queue_switch_fail(err):
            self.dispatch_to_main.emit(lambda e=err: on_fail(e))

        worker = Worker(run_all_with_cancel_check)
        worker.setAutoDelete(False)
        worker.signals.finished.connect(queue_switch_done)
        worker.signals.error.connect(queue_switch_fail)
        self._active_stable_worker = worker
        self.thread_pool.start(worker)

    def _kill_git_processes(self) -> None:
        """取消操作时，及时杀死所有git进程。

        这能防止取消后git fetch/checkout继续后台运行占用资源或产生锁。
        复用GitManager的unlock逻辑，但更激进（杀所有git.exe）。
        """
        try:
            write_error_log("取消操作", "开始终止git进程...")
            # 直接使用GitManager的unlock逻辑（Windows taskkill所有git）
            self.git_manager._unlock_git(Path.cwd())  # 传递任意路径，内部会全局kill
            self.logger.append("已终止git进程，操作取消完成。")
        except Exception as e:
            write_error_log("取消杀进程异常", str(e))
            self.logger.append("取消操作完成（进程终止可能不完全）")

    def _set_business_ui_locked(self, locked: bool) -> None:
        """禁用中央区域与菜单栏业务操作，保留窗口最小化/最大化/关闭。"""
        self._business_operation_locked = locked
        self._apply_business_ui_enabled()

    def _apply_business_ui_enabled(self) -> None:
        locked = self._update_flow_locked or self._business_operation_locked
        central = self.centralWidget()
        if central:
            central.setEnabled(not locked)
        self.menuBar().setEnabled(not locked)
        if hasattr(self, "_action_check_update") and self._action_check_update:
            self._action_check_update.setEnabled(not self._update_flow_locked)

    def set_update_flow_locked(self, locked: bool) -> None:
        """更新下载/安装期间禁用业务操作，保留窗口最小化/最大化/关闭。"""
        self._update_flow_locked = locked
        self._apply_business_ui_enabled()
        if locked:
            self.pause_background_tasks_for_update()
        else:
            self.resume_background_tasks_after_update()

    def pause_background_tasks_for_update(self) -> None:
        """更新流程期间暂停后台任务，避免 git 子进程与 curl 下载并发导致原生崩溃。"""
        self._auto_refresh_timer.stop()
        self._parallel_op_serial += 1
        self._active_parallel_workers.clear()
        self._active_stable_worker = None
        self._kill_git_processes()

    def resume_background_tasks_after_update(self) -> None:
        """更新流程结束后恢复自动刷新定时器。"""
        if not self._update_flow_locked:
            self._auto_refresh_timer.start()

    def _schedule_on_main_thread(self, fn) -> None:
        """将任意可调用对象安全调度到主线程执行（供 UpdateController 等使用）。"""
        self.dispatch_to_main.emit(fn)

    def _execute_in_main_thread(self, fn) -> None:
        """将任意可调用对象安全调度到主线程执行。"""
        try:
            fn()
        except Exception as e:
            write_error_log("主线程调度执行异常", str(e))

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
        dialog.settings_changed.connect(self._apply_settings_to_ui)
        dialog.exec()

    def _apply_settings_to_ui(self) -> None:
        """按当前配置统一应用主题与语言。"""
        self._apply_theme()
        self._apply_language()
        self._update_controller.on_language_changed()

    def _apply_theme(self) -> None:
        """应用浅色/深色主题，确保重启后立即读取到用户设置。"""
        self.setStyleSheet(build_app_stylesheet(self.settings.theme))

    def _apply_language(self) -> None:
        """应用主界面与子面板语言。"""
        language = self.settings.language
        if language == "en":
            self.menuBar().clear()
            file_menu = self.menuBar().addMenu("File")
            file_menu.addAction("Exit", self.close)
            tools_menu = self.menuBar().addMenu("Tools")
            tools_menu.addAction("Feedback", self._show_feedback)
            tools_menu.addAction("Settings", self._show_settings)
            help_menu = self.menuBar().addMenu("Help")
            self._action_check_update = help_menu.addAction(
                get_update_texts("en").menu_check_updates,
                lambda: self._update_controller.run_check(auto=False),
            )
            help_menu.addAction("About", self._show_about)
            self.statusBar().showMessage("Ready")
            self.log_title_label.setText("Runtime Logs (auto cleanup, elapsed time shown)")
            self.clear_log_btn.setToolTip("Clear logs")
        else:
            self.menuBar().clear()
            file_menu = self.menuBar().addMenu("文件")
            file_menu.addAction("退出", self.close)
            tools_menu = self.menuBar().addMenu("工具")
            tools_menu.addAction("反馈", self._show_feedback)
            tools_menu.addAction("设置", self._show_settings)
            help_menu = self.menuBar().addMenu("帮助")
            self._action_check_update = help_menu.addAction(
                get_update_texts("zh").menu_check_updates,
                lambda: self._update_controller.run_check(auto=False),
            )
            help_menu.addAction("关于", self._show_about)
            self.statusBar().showMessage("就绪")
            self.log_title_label.setText("运行日志 (自动清理，显示耗时)")
            self.clear_log_btn.setToolTip("清理日志")
        self.project_panel.apply_language(language)
        self.repo_panel.apply_language(language)
        self.operation_panel.apply_language(language)
        self._update_workspace_header()

    def _show_about(self) -> None:
        ver = self.settings.get("app.version", APP_VERSION)
        QMessageBox.about(
            self,
            "关于",
            f"Git 拉线切线工具 v{ver}\n\n专为多仓库项目设计的批量切分支工具。\n支持 Windows / macOS (Intel & M 芯片)。",
        )

    def _update_workspace_header(self) -> None:
        """更新顶部工程摘要，帮助非开发用户快速理解当前上下文。"""
        if not self.current_project_path:
            if self.settings.language == "en":
                self.statusBar().showMessage("Ready")
            else:
                self.statusBar().showMessage("就绪")
            return
        project = self.project_manager.get_project_by_path(self.current_project_path)
        if not project:
            if self.settings.language == "en":
                self.statusBar().showMessage(f"Current project: {self.current_project_path.name}")
            else:
                self.statusBar().showMessage(f"当前工程：{self.current_project_path.name}")
            return
        repo_count = len(project.repositories)
        if self.settings.language == "en":
            self.statusBar().showMessage(f"Current project: {project.name} | Repositories: {repo_count}")
            return
        self.statusBar().showMessage(f"当前工程：{project.name}  |  仓库数：{repo_count}")

    def _on_log_updated(self, text: str) -> None:
        """处理日志更新信号。

        如果是清空消息则清空UI并追加提示，否则追加单行日志。
        这修复了并行模式下全量日志重复发送导致的性能/崩溃问题。
        """
        if "日志已清空" in text:
            self.log_text.clear_logs()
            self.log_text.append_log(text)
        else:
            self.log_text.append_log(text)

    def _on_log_refresh(self, lines: list[str]) -> None:
        """临时日志移除后重建运行日志区，保留 Git 操作等持久条目。"""
        self.log_text.clear_logs()
        for line in lines:
            self.log_text.append_log(line)

    def closeEvent(self, event) -> None:
        """退出时保存状态；更新流程中会先取消后台下载。"""
        if self._update_controller.is_flow_active():
            self._update_controller.cancel_flow()
        try:
            self._auto_refresh_timer.stop()
        except Exception:
            pass
        self.logger.append("应用退出")
        event.accept()
