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
        return reset_at.strftime("%H:%M:%S")
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


def _offer_from_release(
    release: dict[str, Any],
    current_ver: Version,
    sausage: bool,
) -> Optional[UpdateOffer]:
    """若该 Release 比当前版本新且含本平台资产，构造 ``UpdateOffer``。"""
    tag = release.get("tag_name") or ""
    ver = _parse_tag_version(tag)
    if ver is None or ver <= current_ver:
        return None
    label = _version_label(ver)
    asset_name = expected_asset_name(label, sausage)
    asset = _find_asset(release, asset_name)
    if not asset or not asset.get("browser_download_url"):
        return None
    return UpdateOffer(
        version=label,
        tag_name=tag,
        download_url=str(asset["browser_download_url"]),
        asset_name=asset_name,
        asset_size=int(asset.get("size") or 0),
        release_notes=(release.get("body") or "").strip(),
        release_page_url=(release.get("html_url") or "").strip(),
    )


def _fetch_latest_release_api(repo: str) -> Optional[dict[str, Any]]:
    """``GET /releases/latest``（单次请求）；无 Release 时返回 ``None``。"""
    if not is_valid_github_repo(repo):
        raise UpdateCheckError("invalid_repo_config")
    owner, name = repo.strip().split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/releases/latest"
    resp = requests.get(url, headers=_github_headers(), timeout=30)
    if resp.status_code == 404:
        return None
    if resp.status_code in (401, 403):
        _raise_github_api_error(resp, repo)
    resp.raise_for_status()
    item = resp.json()
    if not isinstance(item, dict) or item.get("draft"):
        return None
    return item


def _fetch_releases_paginated(repo: str, current_ver: Version) -> list[dict[str, Any]]:
    """分页拉取 Releases（跳过 draft）；遇到整页均不新于当前版本时可提前结束。"""
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
            params={"per_page": 30, "page": page},
            timeout=30,
        )
        if resp.status_code in (401, 403, 404):
            _raise_github_api_error(resp, repo)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        page_all_old = True
        for item in batch:
            if item.get("draft"):
                continue
            all_releases.append(item)
            ver = _parse_tag_version(str(item.get("tag_name") or ""))
            if ver is not None and ver > current_ver:
                page_all_old = False
        if page_all_old:
            break
        if len(batch) < 30:
            break
        page += 1
    return all_releases


def _parse_latest_tag_from_web(resp: requests.Response) -> tuple[str, str]:
    """从 ``github.com/.../releases/latest`` 响应解析 ``(tag_name, release_page_url)``。"""
    try:
        content_type = (resp.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            data = resp.json()
            if isinstance(data, dict):
                tag = str(data.get("tag_name") or "").strip()
                page = str(data.get("html_url") or resp.url or "").strip()
                if tag:
                    return tag, page
    except ValueError:
        pass
    final = str(resp.url or "")
    match = re.search(r"/releases/tag/([^/?#]+)", final, re.IGNORECASE)
    if match:
        tag = match.group(1)
        return tag, final.split("?")[0]
    raise UpdateCheckError("network", detail="无法解析 GitHub 最新版本")


def _web_release_asset_url(owner: str, name: str, tag: str, asset_name: str) -> str:
    return f"https://github.com/{owner}/{name}/releases/download/{tag}/{asset_name}"


def probe_release_asset_size(download_url: str) -> int:
    """HEAD 探测 Release 资产大小（字节），失败或未知时返回 0。"""
    return _probe_web_asset(download_url)


def _probe_web_asset(download_url: str) -> int:
    """HEAD 探测资产是否存在，返回 ``Content-Length``（未知时为 0）。"""
    resp = requests.head(download_url, allow_redirects=True, timeout=30)
    if resp.status_code not in (200, 302):
        return -1
    try:
        return int(resp.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        return 0


def check_for_update_via_github_web(
    current_version: Optional[str] = None,
) -> Optional[UpdateOffer]:
    """REST API 限流时经 github.com 检查最新 Release（不占用 API core 配额）。"""
    cur_str = (current_version or APP_VERSION).strip()
    try:
        current_ver = Version(cur_str.lstrip("vV"))
    except InvalidVersion as exc:
        raise UpdateCheckError("invalid_version", detail=cur_str) from exc

    if sys.platform not in ("win32", "darwin"):
        raise UpdateCheckError("unsupported_platform")

    settings = Settings()
    repo = (settings.get("github.repo") or "").strip()
    if not is_valid_github_repo(repo):
        raise UpdateCheckError("invalid_repo_config")
    owner, name = repo.strip().split("/", 1)
    sausage = is_sausage_build()

    resp = requests.get(
        f"https://github.com/{owner}/{name}/releases/latest",
        headers={"Accept": "application/json"},
        allow_redirects=True,
        timeout=30,
    )
    resp.raise_for_status()
    tag, page_url = _parse_latest_tag_from_web(resp)
    ver = _parse_tag_version(tag)
    if ver is None or ver <= current_ver:
        return None
    label = _version_label(ver)
    asset_name = expected_asset_name(label, sausage)
    download_url = _web_release_asset_url(owner, name, tag, asset_name)
    size = _probe_web_asset(download_url)
    if size < 0:
        return None
    return UpdateOffer(
        version=label,
        tag_name=tag,
        download_url=download_url,
        asset_name=asset_name,
        asset_size=max(0, size),
        release_notes="",
        release_page_url=page_url,
    )


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
    sausage = is_sausage_build()

    latest = _fetch_latest_release_api(repo)
    if latest is not None:
        latest_ver = _parse_tag_version(str(latest.get("tag_name") or ""))
        if latest_ver is not None and latest_ver <= current_ver:
            return None
        offer = _offer_from_release(latest, current_ver, sausage)
        if offer is not None:
            return offer

    releases = _fetch_releases_paginated(repo, current_ver)
    if latest is not None:
        latest_tag = latest.get("tag_name")
        releases = [
            r for r in releases
            if r.get("tag_name") != latest_tag
        ]
        releases.insert(0, latest)

    best: Optional[tuple[Version, UpdateOffer]] = None
    for release in releases:
        offer = _offer_from_release(release, current_ver, sausage)
        if offer is None:
            continue
        ver = _parse_tag_version(release.get("tag_name") or "")
        if ver is None:
            continue
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
    if sys.platform == "darwin":
        try:
            offer = check_for_update_via_github_web(current_version)
            clear_rate_limit_backoff(Settings())
            return offer, None
        except UpdateCheckError as exc:
            write_error_log("检查更新失败", f"{exc.code} {exc.context}")
            return None, format_update_check_failure(language, exc.code, **exc.context)
        except RequestException as exc:
            write_error_log("检查更新失败", str(exc))
            return None, format_update_check_failure(language, "network", detail=str(exc))
        except Exception as exc:
            write_error_log("检查更新异常", str(exc))
            return None, format_update_check_failure(language, "unknown", detail=str(exc))

    try:
        offer = check_for_update(current_version)
        clear_rate_limit_backoff(Settings())
        return offer, None
    except UpdateCheckError as exc:
        write_error_log("检查更新失败", f"{exc.code} {exc.context}")
        if exc.code == "rate_limit":
            try:
                offer = check_for_update_via_github_web(current_version)
                clear_rate_limit_backoff(Settings())
                return offer, None
            except UpdateCheckError as web_exc:
                write_error_log(
                    "检查更新 Web 兜底失败",
                    f"{web_exc.code} {web_exc.context}",
                )
            except RequestException as web_exc:
                write_error_log("检查更新 Web 兜底失败", str(web_exc))
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
