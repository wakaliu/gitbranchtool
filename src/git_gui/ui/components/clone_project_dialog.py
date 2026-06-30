"""克隆工程对话框。"""
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import threading
import time
from typing import Any

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...config.settings import Settings
from ...utils.runtime_paths import (
    get_embedded_assets_dir,
    get_executable_dir,
    get_repository_root,
    is_pyinstaller_bundle,
)
from ...core.git_clone import (
    build_clone_command,
    parse_clone_progress_percent,
    CloneOutputThrottle,
    remove_existing_path,
    run_clone_process,
    run_script_style_clone_workflow,
    terminate_clone_process,
)
from ...utils.subprocess_helpers import subprocess_git_command_kwargs


class CloneProjectDialog(QDialog):
    """批量克隆工程对话框，支持内部配置和自定义多仓库克隆。"""

    primary_project_ready = Signal(object)
    log_emitted = Signal(str)
    progress_emitted = Signal(int, int, str)
    batch_finished = Signal(bool, str)

    def __init__(self, parent=None, default_target_dir: Path | None = None):
        super().__init__(parent)
        self.settings = Settings()
        self._is_running = False
        self._cancel_requested = False
        self._active_processes: list[subprocess.Popen] = []
        self._internal_profile = self._load_internal_profile()
        self._default_target_dir = default_target_dir
        self._setup_ui()
        self.apply_language(self.settings.language)
        self._bind_runtime_signals()

    def _setup_ui(self) -> None:
        self.setMinimumSize(860, 760)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        basic_group = QGroupBox()
        basic_layout = QGridLayout(basic_group)
        basic_layout.setContentsMargins(10, 16, 10, 10)
        basic_layout.setHorizontalSpacing(8)
        basic_layout.setVerticalSpacing(8)

        self.target_dir_label = QLabel()
        initial_target_dir = self._default_target_dir or self.settings.get_last_added_dir()
        self.target_dir_input = QLineEdit(str(initial_target_dir))
        self.browse_btn = QPushButton()
        self.browse_btn.clicked.connect(self._browse_target_dir)

        self.project_name_label = QLabel()
        self.project_name_input = QLineEdit()

        self.branch_label = QLabel()
        self.branch_input = QLineEdit()
        self.branch_input.setPlaceholderText("develop")

        self.path_hint_label = QLabel()
        self.path_hint_label.setProperty("role", "secondary")
        self.path_hint_label.setWordWrap(True)

        basic_layout.addWidget(self.target_dir_label, 0, 0)
        basic_layout.addWidget(self.target_dir_input, 0, 1)
        basic_layout.addWidget(self.browse_btn, 0, 2)
        basic_layout.addWidget(self.path_hint_label, 1, 1, 1, 2)
        basic_layout.addWidget(self.project_name_label, 2, 0)
        basic_layout.addWidget(self.project_name_input, 2, 1, 1, 2)
        basic_layout.addWidget(self.branch_label, 3, 0)
        basic_layout.addWidget(self.branch_input, 3, 1, 1, 2)

        config_group = QGroupBox()
        config_layout = QVBoxLayout(config_group)
        config_layout.setContentsMargins(8, 14, 8, 8)
        self.config_tabs = QTabWidget()

        self.internal_tab = QWidget()
        internal_layout = QVBoxLayout(self.internal_tab)
        self.internal_list_hint = QLabel()
        self.internal_list_hint.setProperty("role", "secondary")
        self.internal_repo_list = QListWidget()
        self.internal_repo_list.setSelectionMode(QListWidget.NoSelection)
        internal_layout.addWidget(self.internal_list_hint)
        internal_layout.addWidget(self.internal_repo_list)

        self.custom_tab = QWidget()
        custom_layout = QVBoxLayout(self.custom_tab)
        self.custom_table = QTableWidget(0, 3)
        self.custom_table.setHorizontalHeaderLabels(["Repo", "Relative Path", "Remote URL"])
        self.custom_table.horizontalHeader().setStretchLastSection(True)
        custom_layout.addWidget(self.custom_table)
        custom_btn_layout = QHBoxLayout()
        self.add_row_btn = QPushButton("+")
        self.remove_row_btn = QPushButton("-")
        self.add_row_btn.setProperty("role", "compact")
        self.remove_row_btn.setProperty("role", "compact")
        self.add_row_btn.clicked.connect(self._add_custom_row)
        self.remove_row_btn.clicked.connect(self._remove_custom_row)
        custom_btn_layout.addStretch()
        custom_btn_layout.addWidget(self.add_row_btn)
        custom_btn_layout.addWidget(self.remove_row_btn)
        custom_layout.addLayout(custom_btn_layout)

        if self._internal_profile:
            self.config_tabs.addTab(self.internal_tab, "")
        self.config_tabs.addTab(self.custom_tab, "")
        config_layout.addWidget(self.config_tabs)

        start_row = QHBoxLayout()
        self.start_btn = QPushButton()
        self.start_btn.setProperty("role", "primary")
        self.start_btn.setMinimumHeight(46)
        self.start_btn.clicked.connect(self._start_clone)
        self.shallow_clone_chk = QCheckBox()
        self.shallow_clone_chk.setChecked(False)
        start_row.addWidget(self.start_btn, 1)
        start_row.addWidget(self.shallow_clone_chk)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.log_title = QLabel()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        root_layout.addWidget(basic_group)
        root_layout.addWidget(config_group)
        root_layout.addLayout(start_row)
        root_layout.addWidget(self.progress_bar)
        root_layout.addWidget(self.log_title)
        root_layout.addWidget(self.log_view, 1)

        self.basic_group = basic_group
        self.config_group = config_group
        self._add_default_custom_row()
        self._load_internal_repo_items()

    def _bind_runtime_signals(self) -> None:
        qc = Qt.ConnectionType.QueuedConnection
        self.log_emitted.connect(self._append_log, qc)
        self.progress_emitted.connect(self._update_progress, qc)
        self.batch_finished.connect(self._on_batch_finished, qc)

    def apply_language(self, language: str) -> None:
        """应用中英文文案。"""
        is_en = language == "en"
        self.setWindowTitle("Workspace Generator" if is_en else "批量拉线助手")
        self.basic_group.setTitle("1. Basic Settings" if is_en else "1. 基础设置")
        self.config_group.setTitle("2. Configurations" if is_en else "2. 配置区域")
        self.target_dir_label.setText("Destination:" if is_en else "生成位置:")
        self.project_name_label.setText("Project Name:" if is_en else "工程名:")
        self.branch_label.setText("Branch:" if is_en else "分支:")
        self.browse_btn.setText("Browse..." if is_en else "浏览...")
        self.start_btn.setText("Start Generate" if is_en else "开始拉线 (Generate)")
        self.shallow_clone_chk.setText("Shallow Clone" if is_en else "浅克隆")
        self.log_title.setText("Runtime Logs" if is_en else "运行日志")
        self.path_hint_label.setText(
            "(Create project folder under destination)" if is_en else "(将在该目录下创建新文件夹)"
        )
        self.internal_list_hint.setText(
            "Select repositories to clone (checked by default)." if is_en else "勾选需要克隆的仓库（默认全选）。"
        )
        self.add_row_btn.setToolTip("Add Row" if is_en else "新增仓库")
        self.remove_row_btn.setToolTip("Remove Row" if is_en else "移除仓库")
        if self._internal_profile:
            self.config_tabs.setTabText(0, "Internal Project" if is_en else "香肠派对(内部项目)")
            self.config_tabs.setTabText(1, "Custom Project" if is_en else "自定义 / 其他项目")
        else:
            self.config_tabs.setTabText(0, "Custom Project" if is_en else "自定义 / 其他项目")

    def _resolve_internal_profile_path(self) -> Path | None:
        """解析内部克隆配置：冻结版支持 exe 旁路覆盖，其次内置 bundle；开发版先仓库根再 bundle。"""
        candidates: list[Path] = []
        if is_pyinstaller_bundle():
            candidates.append(get_executable_dir() / "sausage_projects.yaml")
        else:
            candidates.append(get_repository_root() / "sausage_projects.yaml")
        candidates.append(get_embedded_assets_dir() / "sausage_projects.yaml")
        for path in candidates:
            if path.exists():
                return path
        return None

    def _load_internal_profile(self) -> dict[str, Any] | None:
        """加载内部项目配置文件；不存在时返回 None。"""
        profile_path = self._resolve_internal_profile_path()
        if profile_path is None:
            return None
        try:
            with profile_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            repos = data.get("repositories", [])
            if not isinstance(repos, list) or not repos:
                return None
            return {"repositories": repos}
        except Exception:
            return None

    def _browse_target_dir(self) -> None:
        title = "Select Directory" if self.settings.language == "en" else "选择目录"
        folder = QFileDialog.getExistingDirectory(self, title, self.target_dir_input.text().strip())
        if folder:
            self.target_dir_input.setText(folder)

    def _add_default_custom_row(self) -> None:
        self._add_custom_row("client", "", "")

    def _add_custom_row(self, repo_name: str = "", relative_path: str = "", remote_url: str = "") -> None:
        row = self.custom_table.rowCount()
        self.custom_table.insertRow(row)
        self.custom_table.setItem(row, 0, QTableWidgetItem(repo_name))
        self.custom_table.setItem(row, 1, QTableWidgetItem(relative_path))
        self.custom_table.setItem(row, 2, QTableWidgetItem(remote_url))

    def _remove_custom_row(self) -> None:
        row = self.custom_table.currentRow()
        if row >= 0:
            self.custom_table.removeRow(row)

    def _load_internal_repo_items(self) -> None:
        if not self._internal_profile:
            return
        self.internal_repo_list.clear()
        for repo in self._internal_profile["repositories"]:
            display_name = repo.get("name", "repo")
            relative = repo.get("path", "")
            if relative:
                display_name = f"{display_name}  ({relative})"
            item = QListWidgetItem(display_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.internal_repo_list.addItem(item)

    def _build_jobs(self) -> tuple[list[dict[str, str]], Path]:
        target_dir = Path(self.target_dir_input.text().strip())
        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)
        self.settings.save_last_added_dir(str(target_dir))

        if self._internal_profile and self.config_tabs.currentIndex() == 0:
            project_name = self.project_name_input.text().strip() or "sausageman-project"
            client_root = target_dir / project_name
            jobs: list[dict[str, str]] = []
            for index, repo in enumerate(self._internal_profile["repositories"]):
                item = self.internal_repo_list.item(index)
                if item and item.checkState() != Qt.Checked:
                    continue
                relative = repo.get("path", "")
                job_path = client_root if relative == "" else client_root / relative
                jobs.append(
                    {
                        "name": repo.get("name", "repo"),
                        "url": repo.get("remote", ""),
                        "path": str(job_path),
                    }
                )
            if not jobs:
                raise ValueError("No repositories configured")
            return jobs, client_root

        jobs = []
        root_path: Path | None = None
        for row in range(self.custom_table.rowCount()):
            url_item = self.custom_table.item(row, 2)
            rel_item = self.custom_table.item(row, 1)
            name_item = self.custom_table.item(row, 0)
            repo_url = (url_item.text().strip() if url_item else "")
            if not repo_url:
                continue
            rel_path = rel_item.text().strip() if rel_item else ""
            repo_name = name_item.text().strip() if name_item else ""
            inferred = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            project_name = self.project_name_input.text().strip() or inferred or "project"
            abs_path = target_dir / project_name if not rel_path else (target_dir / project_name / rel_path)
            jobs.append({"name": repo_name or inferred, "url": repo_url, "path": str(abs_path)})
            if root_path is None:
                root_path = target_dir / project_name
        if not jobs:
            raise ValueError("No repositories configured")
        return jobs, (root_path or target_dir)

    def _start_clone(self) -> None:
        if self._is_running:
            return
        if not self.target_dir_input.text().strip():
            self._show_info("Please input destination." if self.settings.language == "en" else "请填写生成位置")
            return
        try:
            jobs, root_path = self._build_jobs()
        except ValueError:
            self._show_info("Please configure at least one repository." if self.settings.language == "en" else "请至少配置一个仓库")
            return
        self._is_running = True
        self._cancel_requested = False
        self.start_btn.setEnabled(False)
        self.shallow_clone_chk.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.log_view.clear()
        self._append_log("Start cloning..." if self.settings.language == "en" else "开始克隆...")
        threading.Thread(
            target=self._run_jobs_thread,
            args=(jobs, root_path, self.branch_input.text().strip(), self.shallow_clone_chk.isChecked()),
            daemon=True,
        ).start()

    def _resolve_branch(self, repo_url: str, preferred_branch: str) -> str:
        if preferred_branch:
            return preferred_branch
        for candidate in ("develop", "master"):
            result = subprocess.run(
                ["git", "ls-remote", "--heads", repo_url, candidate],
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
                **subprocess_git_command_kwargs(),
            )
            if result.returncode == 0 and result.stdout.strip():
                return candidate
        return ""

    def _run_jobs_thread(
        self,
        jobs: list[dict[str, str]],
        root_path: Path,
        preferred_branch: str,
        shallow_clone: bool,
    ) -> None:
        total = len(jobs)
        succeeded = 0
        skipped = 0
        failed = 0
        for index, job in enumerate(jobs, start=1):
            if self._cancel_requested:
                break
            url = job["url"]
            target = Path(job["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                self.log_emitted.emit(f"[{index}/{total}] remove existing: {target}")
                try:
                    remove_existing_path(target)
                except Exception as e:
                    failed += 1
                    self.log_emitted.emit(f"  FAIL: remove existing path failed - {e}")
                    self.progress_emitted.emit(index * 100, total * 100, target.name)
                    continue
            branch = self._resolve_branch(url, preferred_branch)
            if shallow_clone:
                cmd = build_clone_command(url, target, branch, True)
                self.log_emitted.emit(f"[{index}/{total}] {' '.join(cmd)}")
                ok, output = self._run_clone_process_streaming(cmd, index, total, job["name"])
            else:
                self.log_emitted.emit(
                    f"[{index}/{total}] script-style clone + fetch + checkout ({branch or 'default'})"
                )
                ok, output = self._run_script_clone_workflow_streaming(
                    url, target, branch, index, total, job["name"],
                )
            if self._cancel_requested:
                break
            if ok:
                succeeded += 1
                self.log_emitted.emit(f"  OK: {job['name']} ({branch or 'default'})")
            else:
                err = output or "unknown error"
                failed += 1
                self.log_emitted.emit(f"  FAIL: {job['name']} - {err}")
            self.progress_emitted.emit(index * 100, total * 100, job["name"])
        completed_ok = succeeded + skipped
        success = (failed == 0) and (not self._cancel_requested)
        if self._cancel_requested:
            summary = "Cancelled by user." if self.settings.language == "en" else "已取消克隆任务。"
        else:
            if self.settings.language == "en":
                summary = f"Completed {completed_ok}/{total}, succeeded {succeeded}, skipped {skipped}, failed {failed}"
            else:
                summary = f"完成 {completed_ok}/{total}，成功 {succeeded}，跳过 {skipped}，失败 {failed}"
        if succeeded > 0 and not self._cancel_requested:
            self.primary_project_ready.emit(root_path)
        self.batch_finished.emit(success, summary)

    def _run_script_clone_workflow_streaming(
        self,
        url: str,
        target: Path,
        branch: str,
        index: int,
        total: int,
        repo_name: str,
    ) -> tuple[bool, str]:
        """全量 clone + fetch + checkout，与 sausage-biu 脚本一致。"""
        repo_percent = 0
        start_time = time.time()
        last_git_status = ""
        throttle = CloneOutputThrottle()

        def _emit_live_progress(elapsed_seconds: int) -> None:
            nonlocal repo_percent
            if repo_percent > 0:
                inferred_percent = repo_percent
            else:
                inferred_percent = min(5, max(1, elapsed_seconds // 30))
            completed_scaled = (index - 1) * 100 + inferred_percent
            if last_git_status:
                title = last_git_status
            elif self.settings.language == "en":
                title = f"{repo_name} waiting for git output... {elapsed_seconds}s"
            else:
                title = f"{repo_name} 等待 git 输出... {elapsed_seconds}s"
            self.progress_emitted.emit(completed_scaled, total * 100, title)

        def on_line(text: str) -> None:
            nonlocal repo_percent, last_git_status
            should_log, should_progress = throttle.on_git_line(text)
            last_git_status = text if len(text) <= 96 else f"{text[:93]}..."
            parsed = parse_clone_progress_percent(text)
            if parsed is not None:
                repo_percent = max(repo_percent, parsed)
            if should_progress:
                _emit_live_progress(int(time.time() - start_time))
            if should_log:
                self.log_emitted.emit(f"[git] {text}")

        def on_heartbeat(elapsed: int) -> None:
            should_log, should_progress = throttle.on_heartbeat()
            if should_progress:
                _emit_live_progress(elapsed)
            if not should_log:
                return
            idle_msg = (
                f"[{index}/{total}] {repo_name} still running ({elapsed}s), no git output yet..."
                if self.settings.language == "en"
                else f"[{index}/{total}] {repo_name} 仍在运行（{elapsed}秒），暂未收到 git 输出..."
            )
            self.log_emitted.emit(idle_msg)

        def on_step(message: str) -> None:
            self.log_emitted.emit(f"[{index}/{total}] {message}")

        ok, output = run_script_style_clone_workflow(
            url,
            target,
            branch,
            cancel_check=lambda: self._cancel_requested,
            line_callback=on_line,
            heartbeat_callback=on_heartbeat,
            step_callback=on_step,
            active_processes=self._active_processes,
        )
        if not ok and output == "cancelled":
            return False, "cancelled"
        return ok, output

    def _run_clone_process_streaming(self, cmd: list[str], index: int, total: int, repo_name: str) -> tuple[bool, str]:
        """流式执行 git clone，将 git 原始输出写入日志并驱动进度条。"""
        repo_percent = 0
        start_time = time.time()
        last_git_status = ""
        throttle = CloneOutputThrottle()

        def _emit_live_progress(elapsed_seconds: int) -> None:
            nonlocal repo_percent
            if repo_percent > 0:
                inferred_percent = repo_percent
            else:
                inferred_percent = min(5, max(1, elapsed_seconds // 30))
            completed_scaled = (index - 1) * 100 + inferred_percent
            if last_git_status:
                title = last_git_status
            elif self.settings.language == "en":
                title = f"{repo_name} waiting for git output... {elapsed_seconds}s"
            else:
                title = f"{repo_name} 等待 git 输出... {elapsed_seconds}s"
            self.progress_emitted.emit(completed_scaled, total * 100, title)

        def on_line(text: str) -> None:
            nonlocal repo_percent, last_git_status
            should_log, should_progress = throttle.on_git_line(text)
            last_git_status = text if len(text) <= 96 else f"{text[:93]}..."
            parsed = parse_clone_progress_percent(text)
            if parsed is not None:
                repo_percent = max(repo_percent, parsed)
            if should_progress:
                _emit_live_progress(int(time.time() - start_time))
            if should_log:
                self.log_emitted.emit(f"[git] {text}")

        def on_heartbeat(elapsed: int) -> None:
            should_log, should_progress = throttle.on_heartbeat()
            if should_progress:
                _emit_live_progress(elapsed)
            if not should_log:
                return
            idle_msg = (
                f"[{index}/{total}] {repo_name} still running ({elapsed}s), no git output yet..."
                if self.settings.language == "en"
                else f"[{index}/{total}] {repo_name} 仍在运行（{elapsed}秒），暂未收到 git 输出..."
            )
            self.log_emitted.emit(idle_msg)

        ok, output = run_clone_process(
            cmd,
            cancel_check=lambda: self._cancel_requested,
            line_callback=on_line,
            heartbeat_callback=on_heartbeat,
            active_processes=self._active_processes,
        )
        if not ok and output == "cancelled":
            return False, "cancelled"
        return ok, output

    def _update_progress(self, completed: int, total: int, title: str) -> None:
        if total <= 0:
            return
        value = int(completed * 100 / total)
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{value}% - {title}")

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def _on_batch_finished(self, success: bool, summary: str) -> None:
        self._is_running = False
        self.start_btn.setEnabled(True)
        self.shallow_clone_chk.setEnabled(True)
        self._append_log(summary)
        if self._cancel_requested:
            return
        if success:
            self._show_info("Clone finished." if self.settings.language == "en" else "克隆完成")
        else:
            self._show_info("Clone finished with failures." if self.settings.language == "en" else "克隆结束，部分仓库失败")

    def _show_info(self, message: str) -> None:
        title = "Info" if self.settings.language == "en" else "提示"
        QMessageBox.information(self, title, message)

    def _terminate_process(self, process: subprocess.Popen) -> None:
        """尽量完整终止 git clone 及其子进程。"""
        terminate_clone_process(process)

    def _terminate_active_git_processes(self) -> None:
        for proc in list(self._active_processes):
            self._terminate_process(proc)
        self._active_processes.clear()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._is_running:
            self._cancel_requested = True
            self._append_log("Closing dialog, terminating clone processes..." if self.settings.language == "en" else "关闭弹窗，正在终止克隆进程...")
            self._terminate_active_git_processes()
        super().closeEvent(event)
