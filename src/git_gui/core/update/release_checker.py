"""从 GitHub Releases 检测可安装的新版本。"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests
from packaging.version import InvalidVersion, Version
from requests.exceptions import RequestException, Timeout

from ...config.constants import APP_VERSION
from ...config.settings import Settings
from ...utils.build_channel import is_sausage_build
from ...utils.github_issue import GitHubIssueReporter
from .check_messages import UpdateCheckFailureText, format_update_check_failure
from ...utils.github_repo_config import is_valid_github_repo
from ...utils.logger import write_error_log
from .update_errors import UpdateCheckError
from .update_throttle import clear_rate_limit_backoff, record_rate_limit_backoff

_TAG_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)", re.IGNORECASE)


@dataclass(frozen=True)
class UpdateOffer:
    """可供下载安装的一次 Release。"""

    version: str
    tag_name: str
    download_url: str
    asset_name: str
    asset_size: int
    release_notes: str
    release_page_url: str


def _parse_tag_version(tag_name: str) -> Optional[Version]:
    """从 tag_name 解析 SemVer，无法解析时返回 None。"""
    match = _TAG_VERSION_RE.match((tag_name or "").strip())
    if not match:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


def _version_label(ver: Version) -> str:
    """用于展示与 config 持久化的版本字符串（无 v 前缀）。"""
    return str(ver)


def expected_asset_name(version_label: str, sausage: bool) -> str:
    """返回当前平台与渠道下 Release 资产应使用的文件名。"""
    if sys.platform == "win32":
        base = "GitPullSwitchTool-Sausage" if sausage else "GitPullSwitchTool"
        return f"{base}-Setup-{version_label}.exe"
    if sys.platform == "darwin":
        return "GitPullSwitchTool-Sausage.dmg" if sausage else "GitPullSwitchTool.dmg"
    return ""


def _github_headers() -> dict[str, str]:
    """复用 Issues 模块的 Token 解析，降低 API 限流风险。"""
    token = GitHubIssueReporter()._effective_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _rate_limit_reset_hint(reset_header: Optional[str]) -> str:
    """将 ``X-RateLimit-Reset`` 转为本地时间提示，解析失败时返回空串。"""
    if not reset_header:
        return ""
    try:
        reset_at = datetime.fromtimestamp(int(reset_header))
        return reset_at.strftime("%H:%M")
    except (ValueError, OSError):
        return ""


def _raise_github_api_error(resp: requests.Response, repo: str) -> None:
    """将 GitHub REST 错误转为 ``UpdateCheckError``。"""
    if resp.status_code == 404:
        raise UpdateCheckError("repo_not_found", repo=repo)
    if resp.status_code == 401:
        raise UpdateCheckError("token_invalid")
    if resp.status_code != 403:
        resp.raise_for_status()
        return

    body: dict[str, Any] = {}
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        pass
    api_msg = str(body.get("message") or "").lower()
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if "rate limit" in api_msg or remaining == "0":
        reset_header = resp.headers.get("X-RateLimit-Reset")
        reset_unix = 0
        try:
            reset_unix = int(reset_header) if reset_header else 0
        except (ValueError, TypeError):
            reset_unix = 0
        raise UpdateCheckError(
            "rate_limit",
            reset_time=_rate_limit_reset_hint(reset_header),
            reset_unix=reset_unix,
        )
    raise UpdateCheckError("repo_forbidden", repo=repo)


def _fetch_releases(repo: str) -> list[dict[str, Any]]:
    """分页拉取仓库 Releases（跳过 draft）。"""
    if not is_valid_github_repo(repo):
        raise UpdateCheckError("invalid_repo_config")
    owner, name = repo.strip().split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/releases"
    headers = _github_headers()
    all_releases: list[dict[str, Any]] = []
    page = 1
    while page <= 10:
        resp = requests.get(
            url,
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        if resp.status_code in (401, 403, 404):
            _raise_github_api_error(resp, repo)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for item in batch:
            if item.get("draft"):
                continue
            all_releases.append(item)
        if len(batch) < 100:
            break
        page += 1
    return all_releases


def _find_asset(release: dict[str, Any], expected_name: str) -> Optional[dict[str, Any]]:
    for asset in release.get("assets") or []:
        if asset.get("name") == expected_name:
            return asset
    return None


def check_for_update(current_version: Optional[str] = None) -> Optional[UpdateOffer]:
    """若存在比当前版本新且含本平台资产的 Release，返回 semver 最大的一条。

    Args:
        current_version: 当前版本号字符串，默认 ``APP_VERSION``。

    Returns:
        ``UpdateOffer`` 或 ``None``。

    Raises:
        RequestException: 网络或 API 错误。
        ValueError: 配置或平台不支持。
    """
    cur_str = (current_version or APP_VERSION).strip()
    try:
        current_ver = Version(cur_str.lstrip("vV"))
    except InvalidVersion as exc:
        raise UpdateCheckError("invalid_version", detail=cur_str) from exc

    if sys.platform not in ("win32", "darwin"):
        raise UpdateCheckError("unsupported_platform")

    settings = Settings()
    repo = (settings.get("github.repo") or "").strip()
    releases = _fetch_releases(repo)
    sausage = is_sausage_build()

    best: Optional[tuple[Version, UpdateOffer]] = None

    for release in releases:
        tag = release.get("tag_name") or ""
        ver = _parse_tag_version(tag)
        if ver is None or ver <= current_ver:
            continue
        label = _version_label(ver)
        asset_name = expected_asset_name(label, sausage)
        asset = _find_asset(release, asset_name)
        if not asset or not asset.get("browser_download_url"):
            continue
        offer = UpdateOffer(
            version=label,
            tag_name=tag,
            download_url=str(asset["browser_download_url"]),
            asset_name=asset_name,
            asset_size=int(asset.get("size") or 0),
            release_notes=(release.get("body") or "").strip(),
            release_page_url=(release.get("html_url") or "").strip(),
        )
        if best is None or ver > best[0]:
            best = (ver, offer)

    if best is None:
        return None
    return best[1]


def check_for_update_safe(
    current_version: Optional[str] = None,
    language: str = "zh",
) -> tuple[Optional[UpdateOffer], Optional[UpdateCheckFailureText]]:
    """包装 ``check_for_update``，将异常转为日志/弹窗文案。"""
    try:
        offer = check_for_update(current_version)
        clear_rate_limit_backoff(Settings())
        return offer, None
    except UpdateCheckError as exc:
        write_error_log("检查更新失败", f"{exc.code} {exc.context}")
        if exc.code == "rate_limit":
            record_rate_limit_backoff(
                Settings(),
                int(exc.context.get("reset_unix") or 0),
            )
        return None, format_update_check_failure(language, exc.code, **exc.context)
    except Timeout:
        return None, format_update_check_failure(language, "timeout")
    except RequestException as exc:
        write_error_log("检查更新失败", str(exc))
        return None, format_update_check_failure(language, "network", detail=str(exc))
    except Exception as exc:
        write_error_log("检查更新异常", str(exc))
        return None, format_update_check_failure(language, "unknown", detail=str(exc))
