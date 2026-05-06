"""GitHub Issues 反馈提交工具。

使用 GitHub REST API 提交反馈。创建 Issue 必须携带有效 Personal Access Token，
否则会返回 401；占位仓库名会导致 404。错误信息需区分网络与鉴权，避免误导用户。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

import requests
from requests.exceptions import RequestException, Timeout

from ..config.settings import Settings
from .credential_store import get_github_token as get_token_from_keyring
from .logger import write_error_log


class GitHubIssueReporter:
    """反馈提交器。

    Token 优先顺序：``set_token`` 显式设置 > **系统钥匙串/凭据管理器** (keyring) >
    环境变量 ``GITHUB_TOKEN`` / ``GIT_GUI_GITHUB_TOKEN`` > ``config.yaml`` 的 ``github.token``。

    推荐钥匙串或环境变量，避免将明文写入仓库目录下的 config（开发版配置在仓库根，易误提交）。
    """

    def __init__(self) -> None:
        self.settings = Settings()
        self._token_override: Optional[str] = None

    def set_token(self, token: str) -> None:
        """测试或运行时覆盖令牌（非空则优先于配置与环境变量）。"""
        self._token_override = token.strip() if token else None

    def _effective_token(self) -> str:
        if self._token_override:
            return self._token_override
        from_keyring = (get_token_from_keyring() or "").strip()
        if from_keyring:
            return from_keyring
        env_tok = (
            os.environ.get("GITHUB_TOKEN", "").strip()
            or os.environ.get("GIT_GUI_GITHUB_TOKEN", "").strip()
        )
        if env_tok:
            return env_tok
        return (self.settings.get("github.token") or "").strip()

    def build_manual_issues_browser_url(self, title: str, body: str) -> Optional[str]:
        """构造可在浏览器中手动新建 Issue 的 URL（供无 Token 或 API 失败时使用）。

        优先使用 ``github.feedback_issues_web_url``（完整地址，可指向任意 Issues 入口）；
        否则在 ``github.repo`` 为有效 ``owner/name`` 时使用 ``/issues/new`` 并附带
        ``title`` / ``body`` 查询参数（长度超限时去掉参数，仅打开空白新建页）。
        """
        explicit = (self.settings.get("github.feedback_issues_web_url") or "").strip()
        repo = (self.settings.get("github.repo") or "").strip()
        base: Optional[str] = None
        if explicit:
            base = explicit.rstrip("/")
        elif repo and "/" in repo and "your-username" not in repo:
            base = f"https://github.com/{repo}/issues/new"
        if not base:
            return None
        if "?" in base:
            return base
        params = {"title": title or "用户反馈", "body": body or ""}
        qs = urlencode(params, quote_via=quote)
        if len(base) + 1 + len(qs) > 7500:
            return base
        return f"{base}?{qs}"

    def submit_feedback(
        self,
        title: str,
        body: str,
        image_paths: Optional[list[Path]] = None,
    ) -> tuple[bool, str, Optional[str]]:
        """提交 Issue 到 GitHub。

        Args:
            title: Issue 标题。
            body: 正文（Markdown）。
            image_paths: 预留；当前 API 未上传图片，仅保持签名兼容。

        Returns:
            ``(成功, 说明, 浏览器备用链接)``。失败时第三项非空则可在 UI 中提供「浏览器打开」；
            成功时第三项为 ``None``。
        """
        _ = image_paths
        manual_url = self.build_manual_issues_browser_url(title, body)
        repo = (self.settings.get("github.repo") or "").strip()
        if not repo or "your-username" in repo:
            return False, (
                "尚未配置有效的 GitHub 仓库。\n\n"
                "请在 config.yaml 中将 github.repo 改为「所有者/仓库名」"
                "（例如 octocat/Hello-World），并保存后重试。\n\n"
                "若暂时无法配置 API 仓库，可设置 github.feedback_issues_web_url 为"
                "完整的 Issues 网页地址，以便使用「在浏览器中打开」手动反馈。"
            ), manual_url

        token = self._effective_token()
        if not token:
            return False, (
                "未配置 GitHub 访问令牌，无法创建 Issue。\n\n"
                "请任选其一：\n"
                "• 【推荐】在「工具 → 设置」中保存到系统钥匙串，或设置环境变量 GITHUB_TOKEN\n"
                "• 或在 config.yaml 中设置 github.token（开发时勿将含 Token 的配置提交到 Git）\n"
                "• 或点击下方「在浏览器中打开 Issues」手动提交\n\n"
                "创建令牌：https://github.com/settings/tokens"
            ), manual_url

        url = f"https://api.github.com/repos/{repo}/issues"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}",
        }

        issue_data: dict = {
            "title": title or "用户反馈 - Git拉线切线工具",
            "body": body or "无详细描述",
        }
        labels = self.settings.get("github.issue_labels")
        if isinstance(labels, list) and labels:
            issue_data["labels"] = labels

        try:
            response = requests.post(url, json=issue_data, headers=headers, timeout=20)
        except Timeout:
            write_error_log("GitHub反馈", f"timeout POST {url}")
            return False, "连接 GitHub 超时，请检查网络或代理后重试。", manual_url
        except RequestException as e:
            write_error_log("GitHub反馈", f"request error: {e!r}")
            return False, (
                "无法连接到 GitHub（网络或代理异常）。\n\n"
                "请检查本机网络、系统代理或防火墙后重试。"
            ), manual_url
        except Exception as e:
            write_error_log("GitHub反馈", f"unexpected: {e!r}")
            return False, f"提交过程出现异常：{e}", manual_url

        if response.status_code in (200, 201):
            return True, "", None

        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = (payload.get("message") or "").strip()
                errs = payload.get("errors")
                if isinstance(errs, list) and errs:
                    first = errs[0]
                    if isinstance(first, dict) and first.get("message"):
                        detail = f"{detail} ({first['message']})".strip()
        except Exception:
            detail = response.text[:300].strip()

        write_error_log(
            "GitHub反馈",
            f"status={response.status_code} url={url}\n{detail or response.text[:500]}",
        )

        if response.status_code == 401:
            return False, (
                "GitHub 拒绝了令牌（401）。\n\n"
                "请确认 github.token 未过期，且对目标仓库具有创建 Issue 的权限。"
            ), manual_url
        if response.status_code == 403:
            return False, (
                "没有权限在该仓库创建 Issue（403）。\n\n"
                "请确认 Token 作用域包含 repo / public_repo，且对仓库有写权限。"
            ), manual_url
        if response.status_code == 404:
            return False, (
                "仓库不存在或无法访问（404）。\n\n"
                "请检查 github.repo 是否为「所有者/仓库名」，以及 Token 是否能访问该库。"
            ), manual_url
        if response.status_code == 422:
            hint = detail or "请求格式或标签不被接受"
            return False, (
                f"GitHub 未接受本次提交（422）：{hint}\n\n"
                "若配置了 github.issue_labels，请确认仓库中已存在对应标签，"
                "或暂时清空 issue_labels 后重试。"
            ), manual_url

        return False, (
            f"提交失败（HTTP {response.status_code}）。\n\n"
            f"{detail or '无详细说明，请查看 logs/app-error.log'}"
        ), manual_url
