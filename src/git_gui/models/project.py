"""工程 (Project) 数据模型。

一个工程目录下可能包含多个 Git 仓库 (如 Unity 项目 Assets/ 和 Library/ 下的子仓库)。
支持拖拽排序持久化。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from .repository import GitRepository

@dataclass
class Project:
    """工程模型。

    为什么把 repositories 作为属性而非实时扫描：允许用户调整仓库显示顺序，
    减少重复扫描，提高响应速度。
    """
    path: Path
    name: str = ""
    repositories: List[GitRepository] = field(default_factory=list)
    is_expanded: bool = True

    def __post_init__(self):
        if not self.name:
            self.name = self.path.name

    def add_repository(self, repo: GitRepository) -> None:
        """避免重复添加相同路径的仓库。"""
        if not any(r.path == repo.path for r in self.repositories):
            self.repositories.append(repo)

    def get_repo_by_path(self, repo_path: Path) -> Optional[GitRepository]:
        for repo in self.repositories:
            if repo.path == repo_path:
                return repo
        return None

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.name,
            "repositories": [r.to_dict() for r in self.repositories],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        project = cls(
            path=Path(data["path"]),
            name=data.get("name", ""),
        )
        for repo_data in data.get("repositories", []):
            project.add_repository(GitRepository.from_dict(repo_data))
        return project
