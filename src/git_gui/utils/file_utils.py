"""文件和 Git 仓库检测工具。

专注于纯路径操作和仓库识别，保持单一职责。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .subprocess_helpers import subprocess_git_command_kwargs, subprocess_hide_console_kwargs

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
            **subprocess_git_command_kwargs(),
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


def get_remote_url(repo_path: Path) -> str:
    """读取 origin 远程 URL，失败时返回空字符串。

    Args:
        repo_path: 仓库根目录。

    Returns:
        origin 远程地址；未配置或命令失败时为空字符串。
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            **subprocess_git_command_kwargs(),
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def normalize_repo_path_key(path: Path | str) -> str:
    """统一仓库路径键，避免 Windows/macOS 下大小写、符号链接差异导致匹配遗漏。"""
    p = Path(path)
    try:
        resolved = p.resolve()
    except (OSError, RuntimeError):
        resolved = p
    try:
        if resolved.exists():
            st = os.stat(resolved, follow_symlinks=True)
            return f"{int(st.st_dev)}:{int(st.st_ino)}"
    except OSError:
        pass
    text = os.path.normcase(str(resolved))
    if sys.platform == "darwin":
        text = text.casefold()
    return text


def paths_refer_to_same_location(left: Path | str, right: Path | str) -> bool:
    """判断两路径是否指向同一目录（macOS 大小写不敏感卷上也能正确匹配）。"""
    if normalize_repo_path_key(left) == normalize_repo_path_key(right):
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def resolve_primary_repository_path(
    project_path: Path | str,
    repositories: list,
) -> Path | None:
    """解析工程的主仓库路径（瘦身等操作需排除）。

    优先匹配 ``project_path`` 本身；若工程目录不是 Git 仓（如 sausage 工程根为
    ``client_ios1``、主仓在 ``client_ios1/ios``），则取列表首行主仓库。
    """
    project = Path(project_path)
    repo_paths: list[Path] = []
    for repo in repositories:
        repo_path = repo.path if hasattr(repo, "path") else Path(repo)
        repo_paths.append(repo_path)
        if paths_refer_to_same_location(repo_path, project):
            return repo_path
    if is_git_repository(project):
        try:
            return project.resolve()
        except (OSError, RuntimeError):
            return project
    if repo_paths:
        return repo_paths[0]
    return None


def _as_scan_path(path: Path) -> Path:
    """Windows 长路径仓库需加 ``\\\\?\\`` 前缀，否则深层目录统计可能漏计为 0。"""
    if os.name != "nt":
        return path
    try:
        resolved = str(path.resolve())
    except (OSError, RuntimeError):
        resolved = str(path)
    if resolved.startswith("\\\\?\\"):
        return Path(resolved)
    if resolved.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + resolved[2:])
    return Path("\\\\?\\" + resolved)


def _get_directory_size_scandir(path: Path) -> int:
    """基于 scandir 的跨平台目录体积统计。"""
    scan_path = _as_scan_path(path)
    if not scan_path.exists() and not path.exists():
        return 0
    if not scan_path.exists():
        scan_path = path
    total = 0
    stack = [scan_path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue
    return total


def _path_has_entries(path: Path) -> bool:
    """快速判断目录是否非空，用于校验平台统计结果。"""
    try:
        with os.scandir(path) as entries:
            return next(entries, None) is not None
    except (OSError, PermissionError):
        return False


def _get_directory_size_powershell(path: Path) -> int:
    """Windows 下通过 PowerShell 聚合文件大小，大目录通常比纯 Python 遍历更快。"""
    env = os.environ.copy()
    env["GT_SIZE_PATH"] = str(path)
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "$p = $env:GT_SIZE_PATH; "
                "if (-not (Test-Path -LiteralPath $p)) { Write-Output 0; exit 0 }; "
                "$sum = (Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | "
                "Measure-Object -Property Length -Sum).Sum; "
                "if ($null -eq $sum) { Write-Output 0 } else { Write-Output ([int64]$sum) }",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            env=env,
            **subprocess_hide_console_kwargs(),
        )
        if result.returncode != 0:
            return _get_directory_size_scandir(path)
        value = (result.stdout or "").strip().splitlines()
        raw = value[-1].strip() if value else ""
        if not raw or raw.lower() in {"nan", "none"}:
            if _path_has_entries(path):
                return _get_directory_size_scandir(path)
            return 0
        size = int(float(raw))
        if size <= 0 and _path_has_entries(path):
            return _get_directory_size_scandir(path)
        return size
    except Exception:
        return _get_directory_size_scandir(path)


def _get_directory_size_du(path: Path) -> int:
    """Unix 下使用 du 快速统计目录体积。"""
    system = platform.system().lower()
    if system == "darwin":
        cmd = ["du", "-sk", str(path)]
        multiplier = 1024
    else:
        cmd = ["du", "-sb", str(path)]
        multiplier = 1
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            **subprocess_git_command_kwargs(),
        )
        if result.returncode != 0:
            return _get_directory_size_scandir(path)
        parts = (result.stdout or "").strip().split()
        if not parts:
            if _path_has_entries(path):
                return _get_directory_size_scandir(path)
            return 0
        size = int(parts[0]) * multiplier
        if size <= 0 and _path_has_entries(path):
            return _get_directory_size_scandir(path)
        return size
    except Exception:
        return _get_directory_size_scandir(path)


def get_directory_size(path: Path) -> int:
    """统计目录占用字节数。

    Unity 工程常含父子嵌套 Git 仓库，并行扫描会导致 IO 争用并出现 0 B 或严重偏小；
    统一使用 scandir 逐文件累加，并在 Windows 上启用长路径前缀。

    Args:
        path: 待统计目录。

    Returns:
        目录总字节数；路径不存在时返回 0。
    """
    if not path.exists():
        return 0
    size = _get_directory_size_scandir(path)
    if size <= 0 and _path_has_entries(path):
        size = _get_directory_size_scandir(path.resolve())
    return size


def get_directory_sizes_parallel(
    paths: List[Path],
    max_workers: int = 4,
    cancel_check=None,
) -> dict[str, int]:
    """并行统计多个目录的磁盘占用。

    Args:
        paths: 待统计目录列表。
        max_workers: 最大并发线程数。
        cancel_check: 返回 True 时停止提交新任务并尽快结束。

    Returns:
        路径字符串到字节数的映射。
    """
    if not paths:
        return {}
    workers = max(1, min(max_workers, len(paths)))
    results: dict[str, int] = {}

    def _scan_one(target: Path) -> tuple[str, int]:
        return str(target), get_directory_size(target)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_scan_one, path): path for path in paths}
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                for pending in futures:
                    pending.cancel()
                break
            try:
                key, size = future.result()
                results[key] = size
            except Exception:
                path = futures[future]
                results[str(path)] = 0
    return results


def format_bytes(size: int) -> str:
    """将字节数格式化为人类可读字符串。

    Args:
        size: 字节数。

    Returns:
        如 ``1.2 GB``、``450 MB``；负数按 0 处理。
    """
    value = max(0, int(size))
    units = ("B", "KB", "MB", "GB", "TB")
    if value < 1024:
        return f"{value} B"
    unit_index = 0
    scaled = float(value)
    while scaled >= 1024 and unit_index < len(units) - 1:
        scaled /= 1024
        unit_index += 1
    if unit_index <= 1:
        return f"{scaled:.0f} {units[unit_index]}"
    return f"{scaled:.1f} {units[unit_index]}"


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
            **subprocess_git_command_kwargs(),
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
