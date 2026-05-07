"""工程管理核心。

负责添加/移除工程、扫描 Git 仓库、维护顺序。
"""
from pathlib import Path
import time
from typing import Collection, List, Optional
from ..models.project import Project
from ..models.repository import GitRepository
from ..config.settings import Settings
from ..utils.file_utils import (
    find_git_repositories,
    get_current_branch,
    get_sync_status,
    get_last_commit_timestamp,
)

class ProjectManager:
    """工程和仓库管理。

    为什么单独一个类：将 UI 事件与扫描逻辑分离，便于测试和未来扩展 (e.g. 忽略列表)。
    """
    def __init__(self):
        self.settings = Settings()
        self.projects: List[Project] = []
        self._load_projects_shell()

    def _load_projects_shell(self) -> None:
        """从配置恢复工程路径与名称，不扫描磁盘上的 Git 仓库。

        全量扫描在启动阶段放到后台线程，避免主线程阻塞导致窗口迟迟不出现；
        大工程（如 Unity）下递归目录与逐仓库 git 调用可达数秒以上。
        """
        recent_paths = self.settings.get_recent_projects()
        self.projects.clear()
        for p in recent_paths:
            path = Path(p)
            if path.exists():
                self.projects.append(Project(path=path))

    def scan_projects_for_paths(self, paths: List[Path]) -> None:
        """对给定路径对应的已加载工程执行全量扫描并写回配置。

        供启动后台任务使用：在子线程中调用，仅触碰各自 Project 与只读配置查询，
        完成后由主线程刷新 UI。paths 应在进入线程前从 ``list(projects)`` 拷贝。
        """
        for path in paths:
            project = self.get_project_by_path(path)
            if project:
                self._scan_project(project)
        self._save_projects()

    def add_project(self, path: Path) -> Optional[Project]:
        """添加新工程并立即扫描（扫描操作可能耗时，调用方应在后台线程中执行）。"""
        if not path.exists() or not path.is_dir():
            return None

        if any(p.path == path for p in self.projects):
            return None  # 已存在

        project = Project(path=path)
        self._scan_project(project)  # 此处是耗时点
        self.projects.append(project)
        self._save_projects()
        return project

    def remove_project(self, path: Path) -> bool:
        """移除工程。"""
        self.projects = [p for p in self.projects if p.path != path]
        self._save_projects()
        return True

    def _scan_project(self, project: Project) -> None:
        """扫描工程目录下的所有 Git 仓库，根仓库优先。

        为什么耗时：Unity 项目通常有大量子目录，递归扫描 + 每次调用 get_current_branch() 会产生大量文件 I/O。
        已通过 scandir + 跳过无关目录优化。
        """
        project.repositories.clear()
        repo_paths = find_git_repositories(project.path)

        for repo_path in repo_paths:
            branch = get_current_branch(repo_path)
            status, ahead_count, behind_count = get_sync_status(repo_path)
            repo = GitRepository(
                path=repo_path,
                current_branch=branch,
                status=status,
                ahead_count=ahead_count,
                behind_count=behind_count,
            )
            project.add_repository(repo)
        self._apply_saved_repo_order(project)

    def _apply_saved_repo_order(self, project: Project) -> None:
        """按配置恢复仓库自定义顺序（主仓库固定第一）。"""
        saved = self.settings.get_repo_order(str(project.path))
        if not saved or not project.repositories:
            return
        by_path = {str(r.path): r for r in project.repositories}
        root_repo = by_path.get(str(project.path))
        ordered: list[GitRepository] = []
        if root_repo:
            ordered.append(root_repo)
        for p in saved:
            if p == str(project.path):
                continue
            repo = by_path.get(p)
            if repo and repo not in ordered:
                ordered.append(repo)
        for repo in project.repositories:
            if repo not in ordered:
                ordered.append(repo)
        project.repositories = ordered

    def refresh_all(self) -> None:
        """刷新所有工程的仓库列表。"""
        for project in self.projects:
            self._scan_project(project)
        self._save_projects()

    def get_project_by_path(self, project_path: Path) -> Optional[Project]:
        """按路径查找工程。"""
        for project in self.projects:
            if project.path == project_path:
                return project
        return None

    def refresh_sync_state_for_paths(self, repo_paths: Collection[Path]) -> None:
        """对已登记的仓库重算当前分支与同步列，不重扫工程目录。

        一键切线等操作会改变 HEAD 与远端关系，但全量 refresh_all 成本高；
        仅对本次涉及的仓库调用 get_sync_status，使列表与 git 输出一致。
        """
        targets = set(repo_paths)
        if not targets:
            return
        for project in self.projects:
            for repo in project.repositories:
                if repo.path in targets:
                    repo.current_branch = get_current_branch(repo.path)
                    status, ahead_count, behind_count = get_sync_status(repo.path)
                    repo.status = status
                    repo.ahead_count = ahead_count
                    repo.behind_count = behind_count

    def is_project_inactive(self, project_path: Path, stale_days: int = 7) -> bool:
        """判断工程是否不活跃：全部仓库最近提交都早于阈值。"""
        project = self.get_project_by_path(project_path)
        if not project or not project.repositories:
            return False
        latest_commit = 0.0
        for repo in project.repositories:
            commit_ts = get_last_commit_timestamp(repo.path)
            if commit_ts:
                latest_commit = max(latest_commit, commit_ts)
        if latest_commit <= 0:
            return False
        stale_seconds = stale_days * 24 * 60 * 60
        return (time.time() - latest_commit) > stale_seconds

    def refresh_project_repo_statuses(self, project_path: Path) -> int:
        """只刷新工程内仓库状态，不重扫目录结构。"""
        project = self.get_project_by_path(project_path)
        if not project:
            return 0
        refreshed = 0
        for repo in project.repositories:
            repo.current_branch = get_current_branch(repo.path)
            status, ahead_count, behind_count = get_sync_status(repo.path)
            repo.status = status
            repo.ahead_count = ahead_count
            repo.behind_count = behind_count
            refreshed += 1
        return refreshed

    def _save_projects(self) -> None:
        """保存工程路径顺序到配置。"""
        paths = [str(p.path) for p in self.projects]
        self.settings.save_recent_projects(paths)

    def get_all_repositories(self) -> List[GitRepository]:
        """返回所有工程下的所有仓库 (用于批量操作)。"""
        repos = []
        for project in self.projects:
            repos.extend(project.repositories)
        return repos

    def get_selected_repositories(self, selected_paths: List[Path]) -> List[GitRepository]:
        """根据选中的路径返回对应仓库对象。"""
        all_repos = self.get_all_repositories()
        return [r for r in all_repos if r.path in selected_paths]

    def update_repo_order(self, project_path: Path, ordered_repo_paths: List[Path]) -> None:
        """更新并持久化某工程的仓库顺序（主仓库固定第一）。"""
        for project in self.projects:
            if project.path != project_path:
                continue
            by_path = {r.path: r for r in project.repositories}
            root_repo = by_path.get(project.path)
            ordered: list[GitRepository] = []
            if root_repo:
                ordered.append(root_repo)
            for p in ordered_repo_paths:
                if p == project.path:
                    continue
                repo = by_path.get(p)
                if repo and repo not in ordered:
                    ordered.append(repo)
            for repo in project.repositories:
                if repo not in ordered:
                    ordered.append(repo)
            project.repositories = ordered
            self.settings.save_repo_order(str(project.path), [str(r.path) for r in project.repositories])
            return
