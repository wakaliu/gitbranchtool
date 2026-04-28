"""文件和 Git 仓库检测工具。

专注于纯路径操作和仓库识别，保持单一职责。
"""
from pathlib import Path
from typing import List, Optional
import os
import subprocess
import time

def is_git_repository(path: Path) -> bool:
    """判断目录是否为有效 Git 仓库。

    检查 .git 目录是否存在且为目录 (非文件)。
    为什么不依赖 git 命令：启动更快，适合批量扫描。
    """
    git_dir = path / ".git"
    return git_dir.exists() and git_dir.is_dir()

def find_git_repositories(root_path: Path, max_depth: int = 5) -> List[Path]:
    """递归查找 Git 仓库，优先把根目录仓库排在最前面。

    优化点：
    - 增加 max_depth 默认值到 5（Unity 项目嵌套较深）
    - 使用 os.scandir() 替代 iterdir()，性能显著提升（减少系统调用）
    - 跳过常见大型无关目录（如 node_modules、.cache、Library/Obj 等）
    """
    from os import scandir
    repos: List[Path] = []
    skip_dirs = {".git", "node_modules", "__pycache__", "build", "dist", ".cache", "Temp"}

    # 首先检查根目录本身
    if is_git_repository(root_path):
        repos.append(root_path)

    def scan(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            with scandir(current) as it:
                for entry in it:
                    if entry.name in skip_dirs or (entry.name.startswith(".") and entry.name != ".git"):
                        continue
                    if entry.is_dir():
                        entry_path = Path(entry.path)
                        if is_git_repository(entry_path):
                            if entry_path not in repos:
                                repos.append(entry_path)
                            # Unity 项目存在仓库内再嵌套仓库（如 Script/Biubiubiu2），
                            # 命中后仍需继续向下扫描，避免漏仓。
                            scan(entry_path, depth + 1)
                        else:
                            scan(entry_path, depth + 1)
        except PermissionError:
            pass  # 忽略无权限目录
        except OSError:
            pass  # 忽略其他文件系统错误

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
                return content.removeprefix("ref: refs/heads/")
            return content[:20]  # detached HEAD 情况
    except Exception:
        pass
    return "HEAD"

def get_sync_status(repo_path: Path) -> tuple[str, int, int]:
    """获取同步状态 (status, ahead_count, behind_count)。

    status:
    - synced: 本地与远端一致
    - behind: 本地落后远端
    - ahead: 本地领先远端
    - diverged: 本地和远端都有新提交
    - unknown: 无法判断（例如未设置上游分支）
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if result.returncode != 0:
            return ("unknown", 0, 0)
        parts = result.stdout.strip().split()
        if len(parts) != 2:
            return ("unknown", 0, 0)
        ahead = int(parts[0])
        behind = int(parts[1])
        if ahead == 0 and behind == 0:
            return ("synced", 0, 0)
        if ahead > 0 and behind == 0:
            return ("ahead", ahead, 0)
        if ahead == 0 and behind > 0:
            return ("behind", 0, behind)
        return ("diverged", ahead, behind)
    except Exception:
        return ("unknown", 0, 0)


def get_last_commit_timestamp(repo_path: Path) -> Optional[float]:
    """返回仓库最近一次提交时间戳（秒），失败时返回 None。"""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        if not value:
            return None
        ts = float(value)
        # 防止系统时间异常导致未来时间戳干扰活跃度判断
        return min(ts, time.time())
    except Exception:
        return None
