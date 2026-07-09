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
from ..utils.file_utils import get_current_branch, get_directory_size, get_remote_url, format_bytes
from ..utils.logger import write_error_log
from ..utils.subprocess_helpers import subprocess_git_command_kwargs, subprocess_hide_console_kwargs
from .git_clone import (
    _CLONE_MAX_RETRIES,
    begin_reclone_swap,
    build_clone_command,
    commit_reclone_swap,
    rollback_reclone_swap,
    run_clone_command_with_retries,
    run_script_style_clone_workflow,
)

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
                **subprocess_git_command_kwargs(),
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
                        **subprocess_git_command_kwargs(),
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
        - Windows：直接 taskkill /F /IM git.exe 杀所有 git.exe（比 psutil 可靠，避免 AccessDenied）
        - macOS/Linux：仅结束进程名为 ``git`` 或 ``git-*`` 的进程；不得用子串 ``'git' in name``，
          否则会误杀本应用（GitPullSwitchTool 等）及名称含 git 的其他程序。
        - 无论 repo 匹配，都清理当前 repo 的 lock 文件
        - 每次 switch 前强制调用，防止并行操作时 index.lock 竞争
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
                # 非 Windows：仅用进程名判断，禁止 ``'git' in name``（会误杀 GitPullSwitchTool、GitHub 等含子串 git 的进程）。
                def _is_git_worker_process(proc_name: str) -> bool:
                    n = (proc_name or "").lower()
                    return n == "git" or n.startswith("git-")

                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    pname = proc.info.get("name") or ""
                    if not _is_git_worker_process(pname):
                        continue
                    try:
                        proc.kill()
                        killed = True
                        time.sleep(0.5)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        continue

            # 总是清理当前repo的lock文件（后备+主要方案）
            for lock_name in [
                ".git/index.lock",
                ".git/HEAD.lock",
                ".git/refs/heads.lock",
                ".git/config.lock",
            ]:
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

    def _count_unique_changed_paths(self, repo_path: Path) -> int:
        """统计工作区涉及的唯一文件路径数量（相对仓库根）。

        合并 ``git diff --name-only HEAD``（相对 HEAD 的已跟踪变动）与
        ``git ls-files --others --exclude-standard``（未跟踪且未被忽略），
        去重后计数；不依赖 shell 管道，Windows / macOS（Intel / Apple 芯片）一致。
        """
        tracked = self._run_git(repo_path, ["diff", "--name-only", "HEAD"], timeout=60)
        untracked = self._run_git(
            repo_path, ["ls-files", "--others", "--exclude-standard"], timeout=60
        )
        paths: set[str] = set()
        for block in (tracked, untracked):
            if not block or not block.strip():
                continue
            for line in block.splitlines():
                name = line.strip()
                if name:
                    paths.add(name)
        return len(paths)

    def _discard_local_worktree(self, repo_path: Path) -> str:
        """丢弃本地跟踪与未跟踪变动，为强制切线清场。

        使用 ``reset --hard`` 与 ``clean -fd``，与项目内「强制提高成功率」策略一致；
        子进程仍走 ``_run_git``，与 Windows / macOS 上隐藏控制台等封装保持一致。
        """
        parts: List[str] = []
        reset_out = self._run_git(repo_path, ["reset", "--hard", "HEAD"], timeout=120)
        parts.append(f"Discard(reset): {reset_out}")
        clean_out = self._run_git(repo_path, ["clean", "-fd"], timeout=120)
        parts.append(f"Discard(clean): {clean_out}")
        return "\n".join(parts)

    @staticmethod
    def _is_submodule_gitdir(repo_path: Path) -> bool:
        """子模块/嵌套仓的 ``.git`` 为指向 gitdir 的文件，切线流程与独立仓不同。"""
        return (repo_path / ".git").is_file()


    def _run_switch_git(
        self,
        repo_path: Path,
        args: List[str],
        timeout: int = 300,
        *,
        heartbeat_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        """切线步骤专用 git 调用：大仓耗时长时可回传心跳，失败时解锁并重试一次。"""
        cmd = ["git"] + args
        write_error_log("Git命令开始", f"repo={repo_path}\ncmd={' '.join(cmd)}\ntimeout={timeout}")

        def _execute_once() -> tuple[int, str]:
            if heartbeat_callback is None:
                result = subprocess.run(
                    cmd,
                    cwd=str(repo_path),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    **subprocess_git_command_kwargs(),
                )
                text = (result.stdout or "").strip() or (result.stderr or "").strip()
                return result.returncode if result.returncode is not None else 0, text
            proc = subprocess.Popen(
                cmd,
                cwd=str(repo_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **subprocess_git_command_kwargs(),
            )
            start = time.time()
            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                    text = (stdout or "").strip() or (stderr or "").strip()
                    return proc.returncode if proc.returncode is not None else 0, text
                except subprocess.TimeoutExpired:
                    heartbeat_callback(int(time.time() - start))
                    if time.time() - start > timeout:
                        proc.kill()
                        proc.communicate()
                        return -1, f"命令超时: {' '.join(args)}"

        try:
            code, output = _execute_once()
            if code != 0:
                write_error_log(
                    "Git命令失败",
                    f"repo={repo_path}\ncmd={' '.join(cmd)}\ncode={code}\nstderr={output[:400]}",
                )
                if "index.lock" in output or "config.lock" in output or "Another git process" in output:
                    self._unlock_git(repo_path)
                    code, output = _execute_once()
                    write_error_log("Git命令重试完成", f"repo={repo_path}\ncmd={' '.join(cmd)}\ncode={code}")
            write_error_log("Git命令结束", f"repo={repo_path}\ncmd={' '.join(cmd)}\ncode={code}")
            return output
        except FileNotFoundError:
            write_error_log("Git命令异常", f"repo={repo_path}\ncmd={' '.join(cmd)}\nGit 未安装或未加入 PATH")
            return "Git 未安装或未加入 PATH"
        except Exception as e:
            write_error_log("Git命令异常", f"repo={repo_path}\ncmd={' '.join(cmd)}\nerror={e}")
            return f"执行失败: {str(e)}"

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
        切线流程对齐 sausage-biu 脚本：fetch -p ->（子模块/普通仓分支）-> reset --hard origin/branch -> clean。

        工作区规则（``git.switch_max_stash_files`` 可配置，默认 500）：
        - 无变动文件：跳过 stash/丢弃。
        - 唯一变动路径数超过上限：无论是否勾选 Stash，均 ``reset --hard`` + ``clean -fd``，
          避免超大 stash 拖垮性能或失败。
        - 未超上限且勾选 Stash：``stash push -u``（含未跟踪），再切线。
        - 未超上限且未勾选：丢弃本地变动。

        Args:
            repo_path: 仓库根目录。
            target_branch: 目标分支名；空则使用当前分支名（仅更新到远程同分支）。
            stash: 是否在允许时暂存本地修改（受变动规模上限约束）。
            callback: 可选进度回调。

        Returns:
            各步骤输出的拼接文本。
        """
        if not target_branch:
            target_branch = get_current_branch(repo_path)

        def _step(message: str) -> None:
            if callback:
                callback(message)

        # 每次切线前强制解锁，防止并行或残留进程导致index.lock冲突（用户反馈核心原因）
        _step(f"> 开始切线 {repo_path.name} -> {target_branch}")
        self._unlock_git(repo_path)
        write_error_log("切线开始", f"repo={repo_path}\ntarget_branch={target_branch}\nstash={stash}")

        outputs = []

        max_files = int(self.settings.get("git.switch_max_stash_files", 500))
        _step("> 检查工作区变动")
        changed_files = self._count_unique_changed_paths(repo_path)

        if changed_files > 0:
            if changed_files > max_files:
                _step(f"> 本地变动 {changed_files} 个文件，超过上限，强制丢弃")
                outputs.append(
                    f"本地变动文件数 {changed_files} 超过上限 {max_files}，已强制丢弃本地修改（忽略 Stash 勾选）"
                )
                outputs.append(self._discard_local_worktree(repo_path))
            elif stash:
                _step(f"> git stash push -u（{changed_files} 个文件）")
                stash_out = self._run_git(
                    repo_path,
                    ["stash", "push", "-u", "-m", "Auto-stash before switch"],
                    timeout=120,
                )
                outputs.append(f"Stash: {stash_out}")
                if stash_out:
                    _step(f"  stash: {stash_out[:120]}")
            else:
                _step(f"> 丢弃本地修改（{changed_files} 个文件）")
                outputs.append("未勾选 Stash，已丢弃本地修改")
                outputs.append(self._discard_local_worktree(repo_path))

        def _run_step(args: List[str], label: str, timeout: int = 300) -> str:
            _step(f"> git {' '.join(args)}")
            heartbeat = (lambda elapsed: _step(f"  {label} 进行中... {elapsed}s")) if callback else None
            output = self._run_switch_git(repo_path, args, timeout=timeout, heartbeat_callback=heartbeat)
            if output:
                preview = output if len(output) <= 160 else output[:160] + "..."
                _step(f"  {label}: {preview}")
            return output

        fetch_out = _run_step(
            ["fetch", "origin", target_branch, "-p", "-f", "--no-tags"], "fetch", timeout=120,
        )
        outputs.append(f"Fetch: {fetch_out}")

        remote_ref = f"origin/{target_branch}"
        if self._is_submodule_gitdir(repo_path):
            clean_out = _run_step(["clean", "-dfq"], "clean")
            outputs.append(f"Clean: {clean_out}")
            reset_out = _run_step(["reset", "--hard", remote_ref], "reset")
            outputs.append(f"Reset: {reset_out}")
            switch_out = _run_step(["checkout", "--detach", remote_ref], "checkout")
            outputs.append(f"Switch: {switch_out}")
        else:
            checkout_out = _run_step(["checkout", "-f", "-B", target_branch, remote_ref], "checkout")
            outputs.append(f"Checkout: {checkout_out}")
            reset_out = _run_step(["reset", "--hard", remote_ref], "reset")
            outputs.append(f"Reset: {reset_out}")
            clean_out = _run_step(["clean", "-dfq"], "clean")
            outputs.append(f"Clean: {clean_out}")
            switch_out = _run_step(["checkout", "-f", "-B", target_branch], "checkout")
            outputs.append(f"Switch: {switch_out}")

        _step(f"> 切线完成 {repo_path.name}")

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

    def slim_repo(
        self,
        repo_path: Path,
        callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """通过 re-clone 减小本地占用，无 origin 的本地仓库无法执行。

        默认与 sausage-biu 脚本一致：全量 ``git clone`` + ``fetch -f`` + ``checkout -B``。
        ``git.slim_shallow: true`` 时改用 ``--depth 1`` 浅克隆。
        """
        branch = get_current_branch(repo_path)
        if not branch or branch == "HEAD":
            raise RuntimeError(f"{repo_path.name}: 无法确定当前分支，请先 checkout 到有效分支")

        url = get_remote_url(repo_path)
        if not url:
            raise RuntimeError(f"{repo_path.name}: 未配置 origin 远程，无法 re-clone")

        self._unlock_git(repo_path)
        write_error_log("瘦身开始", f"repo={repo_path}\nbranch={branch}\nurl={url}")

        if callback:
            callback(f"正在瘦身 {repo_path.name}（分支 {branch}）...")

        size_before = get_directory_size(repo_path)
        if callback:
            callback(f"当前占用 {format_bytes(size_before)}，准备删除并 re-clone...")

        shallow = bool(self.settings.get("git.slim_shallow", False))
        if callback:
            mode = "浅克隆 (--depth 1)" if shallow else "全量 clone + fetch + checkout（与 biu 脚本一致）"
            callback(f"克隆模式：{mode}")

        line_cb = lambda line: callback(f"  {line}") if callback else None
        heartbeat_cb = lambda elapsed: callback(f"clone 进行中... {elapsed}s") if callback else None
        step_cb = lambda msg: callback(msg) if callback else None

        backup: Optional[Path] = None
        try:
            backup = begin_reclone_swap(repo_path)

            if shallow:
                cmd = build_clone_command(url, repo_path, branch, True, slim=True)
                write_error_log("瘦身 clone", f"repo={repo_path}\ncmd={' '.join(cmd)}")
                ok, output = run_clone_command_with_retries(
                    cmd,
                    repo_path,
                    cancel_check=cancel_check,
                    line_callback=line_cb,
                    heartbeat_callback=heartbeat_cb,
                    step_callback=step_cb,
                )
            else:
                write_error_log(
                    "瘦身 clone",
                    f"repo={repo_path}\nworkflow=script-style\nurl={url}\nbranch={branch}",
                )
                ok, output = run_script_style_clone_workflow(
                    url,
                    repo_path,
                    branch,
                    cancel_check=cancel_check,
                    line_callback=line_cb,
                    heartbeat_callback=heartbeat_cb,
                    step_callback=step_cb,
                    max_clone_retries=_CLONE_MAX_RETRIES,
                    slim=True,
                )
            if not ok:
                if callback and output:
                    callback(f"clone 失败：{output}")
                raise RuntimeError(output or f"{repo_path.name}: clone 失败")

            commit_reclone_swap(backup)
            backup = None
        except Exception:
            if backup is not None:
                rollback_reclone_swap(repo_path, backup)
            raise

        size_after = get_directory_size(repo_path)
        saved = size_before - size_after
        summary = (
            f"{repo_path.name}: {format_bytes(size_before)} -> {format_bytes(size_after)} "
            f"(节省 {format_bytes(saved)})"
        )
        write_error_log("瘦身结束", f"repo={repo_path}\n{summary}")
        if callback:
            callback(summary)
        return summary
