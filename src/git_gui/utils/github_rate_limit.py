"""查询 GitHub REST API 速率限制（``/rate_limit`` 不计入 core 配额）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests
from requests.exceptions import RequestException, Timeout

from .github_issue import GitHubIssueReporter


@dataclass(frozen=True)
class GitHubRateLimitSnapshot:
    """``resources.core`` 速率限制快照。"""

    limit: int
    remaining: int
    used: int
    reset_at: str
    uses_token: bool


def _github_headers() -> dict[str, str]:
    token = GitHubIssueReporter()._effective_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github_rate_limit() -> GitHubRateLimitSnapshot:
    """请求 ``GET /rate_limit`` 并解析 core 资源配额。

    Returns:
        当前 core 限额快照。

    Raises:
        Timeout: 连接超时。
        RequestException: HTTP 或网络错误。
        ValueError: 响应体缺少 core 字段。
    """
    headers = _github_headers()
    resp = requests.get(
        "https://api.github.com/rate_limit",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    core = (resp.json() or {}).get("resources", {}).get("core") or {}
    if "limit" not in core:
        raise ValueError("GitHub 响应中缺少 resources.core")
    reset_ts = int(core.get("reset") or 0)
    reset_at = (
        datetime.fromtimestamp(reset_ts).strftime("%H:%M")
        if reset_ts
        else "—"
    )
    return GitHubRateLimitSnapshot(
        limit=int(core.get("limit") or 0),
        remaining=int(core.get("remaining") or 0),
        used=int(core.get("used") or 0),
        reset_at=reset_at,
        uses_token="Authorization" in headers,
    )


def format_rate_limit_line(snapshot: GitHubRateLimitSnapshot, language: str = "zh") -> str:
    """格式化为设置页单行展示文案。"""
    if language == "en":
        auth = "with token" if snapshot.uses_token else "no token (per public IP)"
        return (
            f"GitHub API (core): {snapshot.remaining} / {snapshot.limit} left, "
            f"resets about {snapshot.reset_at} ({auth})"
        )
    auth = "已使用 Token" if snapshot.uses_token else "未配置 Token（按本机公网 IP 计额）"
    return (
        f"GitHub API（core）：剩余 {snapshot.remaining} / {snapshot.limit}，"
        f"约 {snapshot.reset_at} 重置（{auth}）"
    )


def fetch_github_rate_limit_safe(
    language: str = "zh",
) -> tuple[Optional[str], Optional[str]]:
    """后台线程安全包装：返回 ``(展示行, 错误信息)``。"""
    try:
        snap = fetch_github_rate_limit()
        return format_rate_limit_line(snap, language), None
    except Timeout:
        msg = "连接 GitHub 超时" if language != "en" else "Timed out connecting to GitHub"
        return None, msg
    except RequestException as exc:
        return None, str(exc)
    except (ValueError, KeyError, TypeError) as exc:
        msg = f"解析配额失败：{exc}" if language != "en" else f"Failed to parse rate limit: {exc}"
        return None, msg
