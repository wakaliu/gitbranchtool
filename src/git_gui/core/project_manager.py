"""工程管理核心。

负责添加/移除工程、扫描 Git 仓库、维护顺序。
"""
from pathlib import Path
from typing import List, Optional
from ..models.project import Project
from ..models.repository import GitRepository
from ..config.settings import Settings
from ..utils.file_utils import find_git_repositories, get_current_branch

class ProjectManager:
    """工程和仓库管理。

    为什么单独一个类：将 UI 事件与扫描逻辑分离，便于测试和未来扩展 (e.g. 忽略列表)。
    """
    def __init__(self):
        self.settings = Settings()
        self.projects: List[Project] = []
        self._load_projects()

    def _load_projects(self) -> None:
        """从配置加载最近工程，保持用户调整的顺序。"""
        recent_paths = self.settings.get_recent_projects()
        self.projects.clear()
        for p in recent_paths:
            path = Path(p)
            if path.exists():
                project = Project(path=path)
                self._scan_project(project)
                self.projects.append(project)

    def add_project(self, path: Path) -> Optional[Project]:
        """添加新工程并立即扫描。"""
        if not path.exists() or not path.is_dir():
            return None

        if any(p.path == path for p in self.projects):
            return None  # 已存在

        project = Project(path=path)
        self._scan_project(project)
        self.projects.append(project)
        self._save_projects()
        return project

    def remove_project(self, path: Path) -> bool:
        """移除工程。"""
        self.projects = [p for p in self.projects if p.path != path]
        self._save_projects()
        return True

    def _scan_project(self, project: Project) -> None:
        """扫描工程目录下的所有 Git 仓库，根仓库优先。"""
        project.repositories.clear()
        repo_paths = find_git_repositories(project.path)

        for repo_path in repo_paths:
            branch = get_current_branch(repo_path)
            repo = GitRepository(path=repo_path, current_branch=branch)
            project.add_repository(repo)

    def refresh_all(self) -> None:
        """刷新所有工程的仓库列表。"""
        for project in self.projects:
            self._scan_project(project)
        self._save_projects()

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
