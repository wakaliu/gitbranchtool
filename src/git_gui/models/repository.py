"""Git 仓库数据模型。

保持轻量，只存储必要状态。current_branch 和 status 用于 UI 显示和操作决策。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List
from datetime import datetime

@dataclass
class GitRepository:
    """单个 Git 仓库模型。

    为什么使用 dataclass：代码简洁、可哈希、易于序列化，适合拖拽和列表管理。
    """
    path: Path
    name: str = ""
    current_branch: str = "HEAD"
    last_fetched: Optional[datetime] = None
    is_dirty: bool = False
    status: str = "unknown"  # synced, behind, ahead, diverged
    ahead_count: int = 0
    behind_count: int = 0

    def __post_init__(self):
        if not self.name:
            self.name = self.path.name

    def to_dict(self) -> dict:
        """用于持久化或日志。"""
        return {
            "path": str(self.path),
            "name": self.name,
            "current_branch": self.current_branch,
            "is_dirty": self.is_dirty,
            "status": self.status,
            "ahead_count": self.ahead_count,
            "behind_count": self.behind_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GitRepository":
        path = Path(data["path"])
        return cls(
            path=path,
            name=data.get("name", path.name),
            current_branch=data.get("current_branch", "HEAD"),
            is_dirty=data.get("is_dirty", False),
            status=data.get("status", "unknown"),
            ahead_count=data.get("ahead_count", 0),
            behind_count=data.get("behind_count", 0),
        )
