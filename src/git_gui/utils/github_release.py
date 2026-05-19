"""GitHub Releases API 解析与资产匹配。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests
from packaging.version import InvalidVersion, Version

from ..config.constants import APP_VERSION

_GITHUB_API = "https://api.github.com"
_REQUEST_TIMEOUT = 20
_TAG_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*(?:[a-zA-Z0-9.-]*)?)$", re.IGNORECASE)
_WIN_SETUP_RE = re.compile(r"^GitPullSwitchTool-Setup-.*\.exe$", re.IGNORECASE)


@dataclass(frozen=True)
class ReleaseAssetUrls:
    """某次 Release 上与当前平台相关的下载链接。"""

    release_page_url: str
    windows_installer_url: str | None
    macos_dmg_url: str | None


@dataclass(frozen=True)
class ParsedRelease:
    """从 GitHub API 解析出的发布信息。"""

    version: str
    tag_name: str
    name: str
    body: str
    prerelease: bool
    published_at: str
    assets: ReleaseAssetUrls


class GitHubReleaseError(Exception):
    """GitHub Releases 请求或解析失败。"""


def normalize_repo_slug(repo: str) -> str:
    """将配置中的 repo 规范为 owner/name。"""
    slug = (repo or "").strip().strip("/")
    if not slug or "/" not in slug:
        raise GitHubReleaseError(f"无效的 GitHub 仓库名: {repo!r}")
    if slug.count("/") != 1:
        raise GitHubReleaseError(f"无效的 GitHub 仓库名: {repo!r}")
    return slug


def parse_tag_version(tag_name: str) -> Version:
    """将 tag（如 v1.0.3-beta.1）解析为 packaging.Version。"""
    raw = (tag_name or "").strip()
    match = _TAG_VERSION_RE.match(raw)
    if not match:
        raise InvalidVersion(raw)
    return Version(match.group(1))


def _api_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"GitPullSwitchTool/{APP_VERSION}",
    }


def _get_json(url: str) -> Any:
    try:
        response = requests.get(url, headers=_api_headers(), timeout=_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise GitHubReleaseError("无法连接 GitHub，请检查网络后重试。") from exc
    if response.status_code == 404:
        raise GitHubReleaseError("未找到 Release 信息（仓库可能尚无发布版本）。")
    if response.status_code == 403 and "rate limit" in (response.text or "").lower():
        raise GitHubReleaseError("GitHub API 访问过于频繁，请稍后再试。")
    if response.status_code >= 400:
        raise GitHubReleaseError(f"GitHub API 返回错误 ({response.status_code})。")
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubReleaseError("GitHub API 响应格式异常。") from exc


def _match_asset_urls(html_url: str, assets: list[dict[str, Any]]) -> ReleaseAssetUrls:
    windows_url: str | None = None
    macos_url: str | None = None
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not url:
            continue
        if windows_url is None and _WIN_SETUP_RE.match(name):
            windows_url = url
        elif (
            macos_url is None
            and name.lower().endswith(".dmg")
            and "sausage" not in name.lower()
        ):
            macos_url = url
    return ReleaseAssetUrls(
        release_page_url=html_url,
        windows_installer_url=windows_url,
        macos_dmg_url=macos_url,
    )


def _parse_release_payload(payload: dict[str, Any]) -> ParsedRelease:
    tag_name = str(payload.get("tag_name") or "")
    try:
        version = str(parse_tag_version(tag_name))
    except InvalidVersion as exc:
        raise GitHubReleaseError(f"无法解析版本标签: {tag_name}") from exc
    html_url = str(payload.get("html_url") or "")
    assets = payload.get("assets") or []
    if not isinstance(assets, list):
        assets = []
    return ParsedRelease(
        version=version,
        tag_name=tag_name,
        name=str(payload.get("name") or tag_name),
        body=str(payload.get("body") or ""),
        prerelease=bool(payload.get("prerelease")),
        published_at=str(payload.get("published_at") or ""),
        assets=_match_asset_urls(html_url, assets),
    )


def fetch_latest_stable_release(repo: str) -> ParsedRelease:
    """获取最新正式版（GitHub 排除 prerelease）。"""
    slug = normalize_repo_slug(repo)
    url = f"{_GITHUB_API}/repos/{slug}/releases/latest"
    payload = _get_json(url)
    if not isinstance(payload, dict):
        raise GitHubReleaseError("GitHub API 响应格式异常。")
    return _parse_release_payload(payload)


def fetch_newest_release_including_prerelease(repo: str, *, per_page: int = 30) -> ParsedRelease:
    """在含预发布的列表中取 semver 最大的一条。"""
    slug = normalize_repo_slug(repo)
    url = f"{_GITHUB_API}/repos/{slug}/releases?per_page={per_page}"
    payloads = _get_json(url)
    if not isinstance(payloads, list) or not payloads:
        raise GitHubReleaseError("该仓库暂无 Release。")
    parsed: list[ParsedRelease] = []
    for item in payloads:
        if not isinstance(item, dict):
            continue
        try:
            parsed.append(_parse_release_payload(item))
        except GitHubReleaseError:
            continue
    if not parsed:
        raise GitHubReleaseError("未找到可解析的 Release 版本。")
    parsed.sort(key=lambda r: parse_tag_version(r.tag_name), reverse=True)
    return parsed[0]


def is_newer_version(remote: str, current: str) -> bool:
    """远程版本是否严格大于当前版本。"""
    try:
        return parse_tag_version(remote) > parse_tag_version(current)
    except InvalidVersion:
        return False
