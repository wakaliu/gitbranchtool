"""GitHub 仓库配置校验（避免占位符 repo 导致 API 404）。"""
from __future__ import annotations

DEFAULT_GITHUB_REPO = "wakaliu/gitbranchtool"


def is_valid_github_repo(repo: str) -> bool:
    """是否为可用的 ``owner/name`` 仓库路径。"""
    text = (repo or "").strip()
    if not text or "/" not in text:
        return False
    lower = text.lower().replace("_", "-")
    if "your-username" in lower or "yourusername" in lower.replace("-", ""):
        return False
    if lower.endswith("/git-gui-pull-switch-tool"):
        return False
    return True


def github_repo_config_hint(language: str = "zh") -> str:
    """占位或无效 repo 时的用户提示。"""
    if language == "en":
        return (
            f"Set github.repo in config.yaml to a real repository "
            f"(e.g. {DEFAULT_GITHUB_REPO})."
        )
    return (
        f"请在 config.yaml 中将 github.repo 改为真实仓库 "
        f"（例如 {DEFAULT_GITHUB_REPO}）。"
    )
