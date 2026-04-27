"""Git 操作核心管理器。

所有 git 命令封装在此，优先使用 subprocess 执行原生命令。
支持并行、仅当前分支、自动解锁、强制操作。
"""
import subprocess
from pathlib import Path
import time
import psutil
from typing import List, Dict, Optional, Callable
from ..models.repository import GitRepository
from ..config.settings import Settings
from ..utils.file_utils import get_current_branch

class GitManager:
    """Git 操作核心。

    为什么优先 subprocess 而非 GitPython：更接近原生行为，易于添加 -f 等参数，
    且在 Windows/macOS 上行为一致。
    """
    def __init__(self):
        self.settings = Settings()

    def _run_git(self, repo_path: Path, args: List[str], timeout: int = 30) -> str:
        """执行 git 命令，返回输出。自动处理常见错误。"""
        cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
            if result.returncode != 0:
                # 常见锁错误处理
                if "index.lock" in result.stderr or "Another git process" in result.stderr:
                    self._unlock_git(repo_path)
                    # 重试一次
                    result = subprocess.run(cmd, cwd=str(repo_path), capture_output=True, text=True, timeout=timeout)
            return result.stdout.strip() or result.stderr.strip()
        except subprocess.TimeoutExpired:
            return f"命令超时: {' '.join(args)}"
        except FileNotFoundError:
            return "Git 未安装或未加入 PATH"
        except Exception as e:
            return f"执行失败: {str(e)}"

    def _unlock_git(self, repo_path: Path) -> bool:
        """自动解锁 git 进程锁。

        Windows 使用 taskkill 终止 git.exe，macOS 使用 kill。
        这能显著提高自动化成功率。
        """
        if not self.settings.get("git.auto_unlock", True):
            return False

        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if proc.info['name'] and 'git' in proc.info['name'].lower():
                    try:
                        cmdline = ' '.join(proc.info.get('cmdline', []) or [])
                        if str(repo_path) in cmdline or '.git' in cmdline:
                            proc.kill()
                            time.sleep(0.5)
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            # 尝试删除 lock 文件 (作为后备)
            for lock_name in [".git/index.lock", ".git/HEAD.lock"]:
                lock_file = repo_path / lock_name
                if lock_file.exists():
                    lock_file.unlink(missing_ok=True)
            return True
        except Exception:
            return False

    def get_repository_status(self, repo_path: Path) -> GitRepository:
        """获取或更新仓库状态。"""
        branch = get_current_branch(repo_path)
        repo = GitRepository(path=repo_path, current_branch=branch)

        # 简单检查是否 dirty
        status = self._run_git(repo_path, ["status", "--porcelain"])
        repo.is_dirty = bool(status.strip())
        return repo

    def fetch(self, repo_path: Path, callback: Optional[Callable[[str], None]] = None) -> str:
        """仅 fetch 当前分支，避免拉取所有远程分支 (节省时间和带宽)。"""
        branch = get_current_branch(repo_path)
        args = ["fetch", "origin", branch] + self.settings.get("git.fetch_args", ["--no-tags", "-f"])

        if callback:
            callback(f"正在 fetch {branch} @ {repo_path.name}...")

        output = self._run_git(repo_path, args, timeout=45)
        if callback:
            callback(f"Fetch 完成: {output[:100]}..." if len(output) > 100 else output)
        return output

    def switch(self, repo_path: Path, target_branch: str = "", stash: bool = False, callback: Optional[Callable[[str], None]] = None) -> str:
        """切换分支 (一键切线)。

        逻辑：
        1. 如果有本地修改且勾选 stash，则先 stash
        2. fetch 最新节点
        3. checkout -B <branch> origin/<branch> --force
        使用 -B 和 --force 确保成功率高。
        """
        if not target_branch:
            target_branch = get_current_branch(repo_path)

        if callback:
            callback(f"正在切换到 {target_branch} @ {repo_path.name}...")

        outputs = []

        # Stash 本地修改
        if stash:
            stash_out = self._run_git(repo_path, ["stash", "push", "-m", "Auto-stash before switch"])
            outputs.append(f"Stash: {stash_out}")

        # Fetch
        fetch_out = self._run_git(repo_path, ["fetch", "origin", target_branch, "--no-tags", "-f"])
        outputs.append(f"Fetch: {fetch_out}")

        # 强制切换
        switch_args = ["checkout", "-B", target_branch, f"origin/{target_branch}", "--force"]
        switch_out = self._run_git(repo_path, switch_args)
        outputs.append(f"Switch: {switch_out}")

        result = "\n".join(outputs)
        if callback:
            callback(result[:200] + "..." if len(result) > 200 else result)
        return result

    def run_arbitrary_command(self, repo_path: Path, command: str) -> str:
        """Git 控制台 - 执行任意 git 命令 (供高级用户使用)。"""
        if not command.strip().startswith("git "):
            command = "git " + command.strip()
        args = command.split()[1:]  # 去掉 "git"
        return self._run_git(repo_path, args, timeout=60)
