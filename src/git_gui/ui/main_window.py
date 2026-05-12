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

from ..config.settings import Settings
from ..config.constants import APP_VERSION
from ..core.project_manager import ProjectManager
from ..core.git_manager import GitManager
from ..utils.logger import OperationLogger
from ..utils.logger import write_error_log
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
from .widgets.log_text_edit import LogTextEdit
from .widgets.progress_dialog import OperationProgressDialog
from .theme import build_app_stylesheet

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
            on_log_updated=self._on_log_updated
        )
        self.thread_pool = ThreadPoolManager()
        self.current_selected_repos: list[Path] = []
        self.current_project_path: Path | None = None
        self._active_stable_worker: Worker | None = None
        self._active_parallel_workers: list[Worker] = []
        self._inactive_project_paths: set[Path] = set()
        self._initial_repo_scan_pending: bool = False
        self._auto_refresh_timer = QTimer(self)
        self._auto_refresh_timer.setInterval(5 * 60 * 1000)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_current_project_status)

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

        middle_splitter = QSplitter(Qt.Horizontal)
        middle_splitter.addWidget(self.repo_panel)
        middle_splitter.addWidget(self.operation_panel)
        middle_splitter.setSizes([900, 500])
        middle_layout.addWidget(middle_splitter)
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
        log_layout.setSpacing(8)
        self.log_title_label = QLabel("运行日志 (自动清理，显示耗时)")
        self.log_title_label.setProperty("role", "section-title")
        log_layout.addWidget(self.log_title_label)
        self.log_text = LogTextEdit()
        log_layout.addWidget(self.log_text)

        self.clear_log_btn = QPushButton("清理日志")
        self.clear_log_btn.setProperty("role", "compact")
        self.clear_log_btn.clicked.connect(self.logger.clear)
        log_layout.addWidget(self.clear_log_btn)

        log_wrapper_layout.addWidget(log_group)
        main_splitter.addWidget(log_wrapper_group)
        main_splitter.setSizes([220, 440, 240])
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
            if self.project_manager.projects:
                self._on_project_selected([str(self.project_manager.projects[0].path)])
            self.logger.end_operation(True, f"已添加工程: {project.name}")
            self.statusBar().showMessage(f"工程 {project.name} 添加成功")
        else:
            self.logger.end_operation(False, "添加失败或已存在")

    def _remove_project(self, path: Path) -> None:
        if self.project_manager.remove_project(path):
            self.project_panel.load_projects(self.project_manager.projects)
            self.logger.append(f"已移除工程: {path.name}")

    def _show_clone_dialog(self) -> None:
        """弹出克隆工程对话框并执行克隆。"""
        dialog = CloneProjectDialog(self, default_target_dir=self._default_clone_target_dir())
        dialog.primary_project_ready.connect(self._add_new_project)
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
        self.logger.start_operation("刷新仓库状态")
        if not self.current_project_path:
            self.logger.end_operation(False, "未选择工程")
            return
        refreshed = self.project_manager.refresh_project_repo_statuses(self.current_project_path)
        project = self.project_manager.get_project_by_path(self.current_project_path)
        if project:
            self.repo_panel.load_repositories(project.repositories)
        self._inactive_project_paths.discard(self.current_project_path)
        self.logger.end_operation(True, f"刷新完成：{refreshed} 个仓库")
        self._update_workspace_header()

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

    def _auto_refresh_current_project_status(self) -> None:
        """每 5 分钟自动刷新当前工程仓库状态，跳过不活跃工程。"""
        if not self.current_project_path:
            return
        if self._is_git_operation_running():
            return
        current_path = self.current_project_path
        if self.project_manager.is_project_inactive(current_path, stale_days=7):
            if current_path not in self._inactive_project_paths:
                self._inactive_project_paths.add(current_path)
                self.logger.append(f"{current_path.name} 已标记为不活跃工程，自动刷新暂停。")
            return
        self._inactive_project_paths.discard(current_path)
        refreshed = self.project_manager.refresh_project_repo_statuses(current_path)
        project = self.project_manager.get_project_by_path(current_path)
        if project:
            self.repo_panel.load_repositories(project.repositories)
        if refreshed > 0:
            self.statusBar().showMessage(f"自动刷新完成：{refreshed} 个仓库")

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
        self._run_parallel_git_operation(
            operation_name=action_name,
            repo_paths=selected,
            per_repo_fn=lambda path: self.git_manager.switch(path, target_branch, stash),
            write_result_to_panel=True,
        )

    def _run_parallel_git_operation(
        self,
        operation_name: str,
        repo_paths: List[Path],
        per_repo_fn,
        write_result_to_panel: bool = False,
    ) -> None:
        """统一执行 Git 操作。

        如果 write_result_to_panel=True (一键切线)，使用稳定串行模式 (单个Worker顺序执行，UI更新安全，避免卡住/闪退)。
        否则使用并行 (如Fetch)。按钮状态在所有路径都通过 reset_switch_button 确保重置。
        """
        if not repo_paths:
            return
        self.operation_panel.clear_result()

        if write_result_to_panel:
            self._run_switch_operation_stable(operation_name, repo_paths, per_repo_fn)
            return

        total = len(repo_paths)
        state = {
            "completed": 0,
            "success": 0,
            "failed": 0,
            "results": [],
            "cancelled": False,
            "finalized": False,
            "progress_closed": False,
        }
        self._active_parallel_workers = []

        self.logger.clear()
        self.logger.start_operation(f"{operation_name} ({total} 个仓库)")
        progress = OperationProgressDialog(self, f"正在执行: {operation_name}")
        progress.setWindowModality(Qt.WindowModal)
        progress.update_progress(0, total, f"准备开始，目标仓库: {total}")
        self.operation_panel.btn_switch.setEnabled(False)

        def safe_close_parallel_progress() -> None:
            if state.get("progress_closed"):
                return
            state["progress_closed"] = True
            try:
                progress.blockSignals(True)
            except Exception:
                pass
            try:
                progress.close()
            except Exception:
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
            except Exception as e:
                write_error_log("finalize 异常", f"{operation_name}: {e}")
                try:
                    safe_close_parallel_progress()
                    self.operation_panel.reset_switch_button()
                    self._active_parallel_workers.clear()
                except Exception:
                    pass

        def on_finished(path: Path, output: str) -> None:
            if state["cancelled"] or state["finalized"]:
                return
            state["completed"] += 1
            try:
                write_error_log("并行操作 on_finished", f"{operation_name} repo={path}")
                state["success"] += 1
                message = f"[{path.name}] 成功"
                self.logger.append(message)
                state["results"].append((str(path), True, output))
                if progress.isVisible():
                    progress.update_progress(
                        state["completed"],
                        total,
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
            if state["cancelled"] or state["finalized"]:
                return
            state["completed"] += 1
            try:
                write_error_log("并行操作 on_error", f"{operation_name} repo={path}\n{err[:400] if err else ''}")
                state["failed"] += 1
                self.logger.append(f"[{path.name}] 失败: {err.splitlines()[0] if err else '未知错误'}")
                state["results"].append((str(path), False, err))
                if progress.isVisible():
                    progress.update_progress(
                        state["completed"],
                        total,
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
            """用户点击取消时，立即杀死当前git进程并中断操作。"""
            state["cancelled"] = True
            self._kill_git_processes()
            self.logger.append("用户取消操作，正在终止git进程...")
            self._active_parallel_workers.clear()
            # 使用robust reset确保按钮可用
            self.operation_panel.reset_switch_button()
        progress.canceled.connect(on_cancel)

        for path in repo_paths:
            # 通过线程池限制并发，避免高负载卡顿
            worker = Worker(lambda p=path: per_repo_fn(p))
            worker.setAutoDelete(False)
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

    def _run_switch_operation_stable(self, operation_name: str, repo_paths: List[Path], per_repo_fn) -> None:
        """一键切线稳定串行模式：单个后台Worker顺序执行所有仓库，主线程统一更新UI。

        这避免了并行时多个Worker同时回调导致的Qt事件风暴、33%卡住或闪退。
        每个仓库仍会显示进度和日志，适合长时间git操作。
        """
        total = len(repo_paths)
        state = {"done": False, "cancelled": False, "progress_closed": False}
        self.logger.clear()
        self.logger.start_operation(f"{operation_name} ({total} 个仓库)")
        progress = OperationProgressDialog(self, f"正在执行: {operation_name}")
        progress.setWindowModality(Qt.WindowModal)
        progress.update_progress(0, total, f"准备开始，目标仓库: {total}")
        self.operation_panel.btn_switch.setEnabled(False)
        self.operation_panel.update_result("切线进行中，汇总结果将在完成后显示在此处；详情见下方运行日志。", True)
        write_error_log("稳定串行模式", f"启用切线稳定模式: repos={total}")

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

        def on_stable_cancel() -> None:
            state["cancelled"] = True
            self._kill_git_processes()
            self.logger.append("用户取消切线，正在终止 git 进程…")
            safe_close_progress(rejected=True)
            self.operation_panel.reset_switch_button()

        progress.canceled.connect(on_stable_cancel)

        def emit_progress(index: int, path: Path, ok: bool, text: str) -> None:
            if state["done"]:
                return
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
                self.logger.append(f"--- [{path.name}] 切线成功 ---")
            else:
                self.logger.append(f"--- [{path.name}] 切线失败 ---")
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

        def on_fail(err):
            err_head = err.splitlines()[0] if err else "未知错误"
            self.logger.append(f"批处理异常: {err_head}")
            if err and len(err) > len(err_head):
                for line in err.splitlines()[1:12]:
                    if line.strip():
                        self.logger.append(f"  {line.strip()}")
            self.logger.end_operation(False)
            self.operation_panel.update_result(f"一键切线执行异常：{err_head}", False)
            self._active_stable_worker = None
            safe_close_progress()
            self.operation_panel.reset_switch_button()

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
                    # 每个仓库前强制unlock
                    self.git_manager._unlock_git(path)
                    output = per_repo_fn(path)
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
            help_menu.addAction("About", self._show_about)
            self.statusBar().showMessage("Ready")
            self.log_title_label.setText("Runtime Logs (auto cleanup, elapsed time shown)")
            self.clear_log_btn.setText("Clear Logs")
        else:
            self.menuBar().clear()
            file_menu = self.menuBar().addMenu("文件")
            file_menu.addAction("退出", self.close)
            tools_menu = self.menuBar().addMenu("工具")
            tools_menu.addAction("反馈", self._show_feedback)
            tools_menu.addAction("设置", self._show_settings)
            help_menu = self.menuBar().addMenu("帮助")
            help_menu.addAction("关于", self._show_about)
            self.statusBar().showMessage("就绪")
            self.log_title_label.setText("运行日志 (自动清理，显示耗时)")
            self.clear_log_btn.setText("清理日志")
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

    def closeEvent(self, event) -> None:
        """退出时保存状态。"""
        self.logger.append("应用退出")
        event.accept()
