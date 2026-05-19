"""应用更新检查业务逻辑。"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Literal

from ..config.constants import APP_VERSION
from ..config.settings import Settings
from ..utils.github_release import (
    GitHubReleaseError,
    ParsedRelease,
    fetch_latest_stable_release,
    fetch_newest_release_including_prerelease,
    is_newer_version,
)


@dataclass(frozen=True)
class UpdateInfo:
    """可供 UI 展示的新版本信息。"""

    version: str
    tag_name: str
    name: str
    body: str
    prerelease: bool
    published_at: str
    release_page_url: str
    windows_installer_url: str | None
    macos_dmg_url: str | None


@dataclass(frozen=True)
class UpdateCheckResult:
    """检查更新结果，供 UI 分支处理。"""

    status: Literal["update", "latest", "error"]
    current_version: str
    info: UpdateInfo | None = None
    message: str = ""


def _resolve_github_repo(settings: Settings) -> str:
    override = str(settings.get("update.github_repo", "") or "").strip()
    if override:
        return override
    return str(settings.get("github.repo", "") or "").strip()


def _to_update_info(release: ParsedRelease) -> UpdateInfo:
    return UpdateInfo(
        version=release.version,
        tag_name=release.tag_name,
        name=release.name,
        body=release.body,
        prerelease=release.prerelease,
        published_at=release.published_at,
        release_page_url=release.assets.release_page_url,
        windows_installer_url=release.assets.windows_installer_url,
        macos_dmg_url=release.assets.macos_dmg_url,
    )


def check_for_update(
    *,
    current_version: str | None = None,
    include_prerelease: bool | None = None,
    github_repo: str | None = None,
) -> UpdateCheckResult:
    """查询 GitHub Releases 并判断是否有可升级版本。

    Args:
        current_version: 当前应用版本，默认 APP_VERSION。
        include_prerelease: 是否包含预发布；默认读配置 update.include_prerelease。
        github_repo: 仓库 slug（owner/name）；默认 update.github_repo 或 github.repo。

    Returns:
        UpdateCheckResult: status 为 update / latest / error。
    """
    settings = Settings()
    current = (current_version or APP_VERSION).strip()
    include_pre = (
        include_prerelease
        if include_prerelease is not None
        else bool(settings.get("update.include_prerelease", False))
    )
    repo = (github_repo or _resolve_github_repo(settings)).strip()
    if not repo:
        return UpdateCheckResult(
            status="error",
            current_version=current,
            message="未配置 GitHub 仓库（github.repo）。",
        )

    try:
        release = (
            fetch_newest_release_including_prerelease(repo)
            if include_pre
            else fetch_latest_stable_release(repo)
        )
    except GitHubReleaseError as exc:
        return UpdateCheckResult(
            status="error",
            current_version=current,
            message=str(exc),
        )

    if not is_newer_version(release.version, current):
        return UpdateCheckResult(
            status="latest",
            current_version=current,
            message=release.version,
        )

    return UpdateCheckResult(
        status="update",
        current_version=current,
        info=_to_update_info(release),
    )


def preferred_download_url(info: UpdateInfo) -> str | None:
    """按当前运行平台返回优先打开的下载 URL。"""
    if sys.platform == "win32":
        return info.windows_installer_url or info.release_page_url
    if sys.platform == "darwin":
        return info.macos_dmg_url or info.release_page_url
    return info.release_page_url
