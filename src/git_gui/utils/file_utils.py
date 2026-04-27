"""文件和 Git 仓库检测工具。

专注于纯路径操作和仓库识别，保持单一职责。
"""
from pathlib import Path
from typing import List, Optional
import os

def is_git_repository(path: Path) -> bool:
    """判断目录是否为有效 Git 仓库。

    检查 .git 目录是否存在且为目录 (非文件)。
    为什么不依赖 git 命令：启动更快，适合批量扫描。
    """
    git_dir = path / ".git"
    return git_dir.exists() and git_dir.is_dir()

def find_git_repositories(root_path: Path, max_depth: int = 4) -> List[Path]:
    """递归查找 Git 仓库，优先把根目录仓库排在最前面。

    限制深度避免扫描过深 (Unity 项目常见嵌套)。
    返回的列表中，root_path 本身如果 是仓库会排第一。
    """
    repos: List[Path] = []

    # 首先检查根目录本身
    if is_git_repository(root_path):
        repos.append(root_path)

    def scan(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            for item in current.iterdir():
                if item.name.startswith(".") and item.name != ".git":
                    continue
                if item.is_dir():
                    if is_git_repository(item):
                        if item not in repos:  # 避免重复
                            repos.append(item)
                    else:
                        scan(item, depth + 1)
        except PermissionError:
            pass  # 忽略无权限目录

    scan(root_path, 1)
    return repos

def get_current_branch(repo_path: Path) -> str:
    """快速获取当前分支名，不执行网络操作。

    优先读取 .git/HEAD 文件，避免启动 git 进程。
    """
    head_file = repo_path / ".git" / "HEAD"
    try:
        if head_file.exists():
            content = head_file.read_text(encoding="utf-8").strip()
            if content.startswith("ref: refs/heads/"):
                return content.split("/")[-1]
            return content[:20]  # detached HEAD 情况
    except Exception:
        pass
    return "HEAD"
