"""Git 操作核心管理器。

所有 git 命令封装在此，优先使用 subprocess 执行原生命令。
支持并行、仅当前分支、自动解锁、强制操作。
"""
import subprocess
from pathlib import Path
import time
import psutil
import platform
from typing import List, Dict, Optional, Callable
from ..models.repository import GitRepository
from ..config.settings import Settings
from ..utils.file_utils import get_current_branch
from ..utils.logger import write_error_log
from ..utils.subprocess_helpers import subprocess_hide_console_kwargs

class GitManager:
    """Git 操作核心。

    为什么优先 subprocess 而非 GitPython：更接近原生行为，易于添加 -f 等参数，
    且在 Windows/macOS 上行为一致。
    """
    def __init__(self):
        self.settings = Settings()

    def _run_git(self, repo_path: Path, args: List[str], timeout: int = 45) -> str:
        """执行 git 命令，返回输出。自动处理常见错误。

        默认timeout提高到45s (switch/fetch可单独覆盖)，防止33%卡住。
        """
        cmd = ["git"] + args
        write_error_log("Git命令开始", f"repo={repo_path}\ncmd={' '.join(cmd)}\ntimeout={timeout}")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                **subprocess_hide_console_kwargs(),
            )
            if result.returncode != 0:
                write_error_log("Git命令失败", f"repo={repo_path}\ncmd={' '.join(cmd)}\ncode={result.returncode}\nstderr={result.stderr[:400]}")
                # 常见锁错误处理
                if "index.lock" in result.stderr or "Another git process" in result.stderr:
                    self._unlock_git(repo_path)
                    # 重试一次
                    result = subprocess.run(
                        cmd,
                        cwd=str(repo_path),
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        **subprocess_hide_console_kwargs(),
                    )
                    write_error_log("Git命令重试完成", f"repo={repo_path}\ncmd={' '.join(cmd)}\ncode={result.returncode}")
            write_error_log("Git命令结束", f"repo={repo_path}\ncmd={' '.join(cmd)}\ncode={result.returncode}")
            return result.stdout.strip() or result.stderr.strip()
        except subprocess.TimeoutExpired:
            write_error_log("Git命令超时", f"repo={repo_path}\ncmd={' '.join(cmd)}")
            return f"命令超时: {' '.join(args)}"
        except FileNotFoundError:
            write_error_log("Git命令异常", f"repo={repo_path}\ncmd={' '.join(cmd)}\nGit 未安装或未加入 PATH")
            return "Git 未安装或未加入 PATH"
        except Exception as e:
            write_error_log("Git命令异常", f"repo={repo_path}\ncmd={' '.join(cmd)}\nerror={e}")
            return f"执行失败: {str(e)}"

    def _unlock_git(self, repo_path: Path) -> bool:
        """自动解锁 git 进程锁（更激进版，解决并发闪退）。

        针对用户反馈的“旧git进程未杀干净”问题：
        - Windows：直接 taskkill /F /IM git.exe 杀所有git进程（比psutil可靠，避免AccessDenied）
        - 无论repo匹配，都清理当前repo的lock文件
        - 每次switch前强制调用，防止并行操作时index.lock竞争
        这极大提高成功率，尤其多仓库并行场景。
        """
        if not self.settings.get("git.auto_unlock", True):
            return False

        try:
            system = platform.system().lower()
            killed = False

            if system == "windows":
                # Windows更可靠：强制杀所有git.exe（不依赖psutil权限）
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", "git.exe"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                        **subprocess_hide_console_kwargs(),
                    )
                    killed = True
                    time.sleep(0.8)  # 给系统时间释放锁
                except Exception:
                    pass
            else:
                # 非Windows仍用psutil
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    if proc.info.get('name') and 'git' in proc.info['name'].lower():
                        try:
                            proc.kill()
                            killed = True
                            time.sleep(0.5)
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            continue

            # 总是清理当前repo的lock文件（后备+主要方案）
            for lock_name in [".git/index.lock", ".git/HEAD.lock", ".git/refs/heads.lock"]:
                lock_file = repo_path / lock_name
                if lock_file.exists():
                    try:
                        lock_file.unlink(missing_ok=True)
                        killed = True
                    except Exception:
                        pass

            if killed:
                write_error_log("Git解锁", f"已清理 {repo_path.name} 的git进程/锁文件")
            return True
        except Exception as e:
            write_error_log("解锁异常", f"repo={repo_path}, error={e}")
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

        每次操作前强制_unlock_git，解决“旧git进程残留导致并发冲突/闪退”问题。
        逻辑顺序：unlock -> (stash) -> fetch(-f) -> checkout -B --force。
        使用 -B 和 --force 确保即使分支已存在也能成功。
        """
        if not target_branch:
            target_branch = get_current_branch(repo_path)

        # 每次切线前强制解锁，防止并行或残留进程导致index.lock冲突（用户反馈核心原因）
        self._unlock_git(repo_path)
        write_error_log("切线开始", f"repo={repo_path}\ntarget_branch={target_branch}\nstash={stash}")

        if callback:
            callback(f"正在切换到 {target_branch} @ {repo_path.name}...")

        outputs = []

        # Stash 本地修改
        if stash:
            stash_out = self._run_git(repo_path, ["stash", "push", "-m", "Auto-stash before switch"])
            outputs.append(f"Stash: {stash_out}")

        # Fetch (使用 -f 强制更新，timeout增加防卡住)
        fetch_out = self._run_git(repo_path, ["fetch", "origin", target_branch, "--no-tags", "-f"], timeout=60)
        outputs.append(f"Fetch: {fetch_out}")

        # 强制切换分支 (timeout增加，防止长时间卡住)
        switch_args = ["checkout", "-B", target_branch, f"origin/{target_branch}", "--force"]
        switch_out = self._run_git(repo_path, switch_args, timeout=45)
        outputs.append(f"Switch: {switch_out}")

        result = "\n".join(outputs)
        write_error_log("切线结束", f"repo={repo_path}\nresult_preview={result[:400]}")
        if callback:
            callback(result[:200] + "..." if len(result) > 200 else result)
        return result

    def run_arbitrary_command(self, repo_path: Path, command: str) -> str:
        """Git 控制台 - 执行任意 git 命令 (供高级用户使用)。"""
        if not command.strip().startswith("git "):
            command = "git " + command.strip()
        args = command.split()[1:]  # 去掉 "git"
        return self._run_git(repo_path, args, timeout=60)
