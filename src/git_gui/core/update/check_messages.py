"""检查更新失败时的用户文案（中/英），与 UI 层解耦供 core 使用。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...utils.github_repo_config import github_repo_config_hint


@dataclass(frozen=True)
class UpdateCheckFailureText:
    """日志区单行摘要 + 弹窗多行说明。"""

    log_line: str
    dialog_message: str


def format_update_check_failure(language: str, code: str, **context: Any) -> UpdateCheckFailureText:
    """将 ``UpdateCheckError.code`` 映射为日志与弹窗文案。"""
    lang = "en" if language == "en" else "zh"
    reset_time = str(context.get("reset_time") or "").strip()
    repo = str(context.get("repo") or "").strip()
    detail = str(context.get("detail") or "").strip()

    if lang == "en":
        return _format_en(code, reset_time=reset_time, repo=repo, detail=detail)
    return _format_zh(code, reset_time=reset_time, repo=repo, detail=detail)


def _retry_when(reset_time: str, lang: str) -> str:
    if reset_time:
        return f"约 {reset_time} 后再试" if lang == "zh" else f"try again after about {reset_time}"
    return "稍后再试" if lang == "zh" else "try again later"


def _bullet_retry(when: str, lang: str) -> str:
    if lang == "en" and when:
        return f"• {when[0].upper()}{when[1:]}" if when else f"• {when}"
    return f"• {when}"


def _format_zh(
    code: str,
    *,
    reset_time: str,
    repo: str,
    detail: str,
) -> UpdateCheckFailureText:
    when = _retry_when(reset_time, "zh")
    if code == "rate_limit":
        return UpdateCheckFailureText(
            log_line=f"检查更新失败：GitHub 访问过于频繁，{when}",
            dialog_message=(
                "无法向 GitHub 查询新版本（API 与网页兜底均未成功）。\n\n"
                "原因：REST API 配额已用尽（未配置 Token 时同一出口 IP 约 60 次/小时）。"
                "公司网络、代理或本机反复启动/检查会共用该配额，"
                "到提示时间后也可能立刻再次被占满。\n\n"
                "你可以：\n"
                f"{_bullet_retry(when, 'zh')}\n"
                "• 在「工具 → 设置」中配置 GitHub Token（限额约升至 5000 次/小时，推荐）\n"
                "• 关闭「启动时自动检查更新」，测试时勿连续多次点击「检查更新」"
            ),
        )
    if code == "token_invalid":
        return UpdateCheckFailureText(
            log_line="检查更新失败：GitHub Token 无效或已过期",
            dialog_message=(
                "无法向 GitHub 查询新版本。\n\n"
                "原因：已保存的 Token 被拒绝（401）。\n\n"
                "你可以：在「工具 → 设置」中更新或清除 Token 后重试。"
                "若仅检查公开 Release，可清除 Token 后等待限流恢复再试。"
            ),
        )
    if code == "repo_not_found":
        return UpdateCheckFailureText(
            log_line=f"检查更新失败：未找到仓库「{repo}」",
            dialog_message=(
                f"无法向 GitHub 查询新版本。\n\n"
                f"原因：仓库「{repo}」不存在或无法访问（404）。\n\n"
                "你可以：在 config.yaml 中将 github.repo 改为正确的「所有者/仓库名」"
                "（例如 wakaliu/gitbranchtool）。"
            ),
        )
    if code == "repo_forbidden":
        return UpdateCheckFailureText(
            log_line=f"检查更新失败：无权读取「{repo}」的 Release",
            dialog_message=(
                f"无法向 GitHub 查询新版本。\n\n"
                f"原因：对仓库「{repo}」没有读取 Release 的权限（403）。\n\n"
                "你可以：若为私有仓库，在「工具 → 设置」中配置对该仓库有读权限的 Token。"
            ),
        )
    if code == "invalid_repo_config":
        hint = github_repo_config_hint("zh")
        return UpdateCheckFailureText(
            log_line="检查更新失败：github.repo 配置无效",
            dialog_message=f"无法检查更新。\n\n{hint}",
        )
    if code == "timeout":
        return UpdateCheckFailureText(
            log_line="检查更新失败：连接 GitHub 超时",
            dialog_message=(
                "无法向 GitHub 查询新版本。\n\n"
                "原因：连接超时。\n\n"
                "你可以：检查网络、代理或防火墙后重试。"
            ),
        )
    if code == "network":
        extra = f"\n\n详情：{detail}" if detail else ""
        return UpdateCheckFailureText(
            log_line="检查更新失败：无法连接 GitHub",
            dialog_message=(
                "无法向 GitHub 查询新版本。\n\n"
                "原因：网络异常或代理配置问题。"
                f"{extra}\n\n"
                "你可以：确认能访问 github.com 后重试。"
            ),
        )
    if code == "unsupported_platform":
        return UpdateCheckFailureText(
            log_line="检查更新失败：当前系统不支持自动更新",
            dialog_message="当前平台不支持通过本程序自动检查/安装更新。",
        )
    if code == "invalid_version":
        ver = detail or "?"
        return UpdateCheckFailureText(
            log_line=f"检查更新失败：当前版本号无效（{ver}）",
            dialog_message=f"无法检查更新：应用版本号「{ver}」无法解析，请检查配置 app.version。",
        )
    return UpdateCheckFailureText(
        log_line="检查更新失败：未知错误",
        dialog_message=(
            "无法完成更新检查。\n\n"
            f"{detail or '请查看 logs/app-error.log 了解详情。'}"
        ),
    )


def _format_en(
    code: str,
    *,
    reset_time: str,
    repo: str,
    detail: str,
) -> UpdateCheckFailureText:
    when = _retry_when(reset_time, "en")
    if code == "rate_limit":
        return UpdateCheckFailureText(
            log_line=f"Update check failed: GitHub API rate limit; {when}",
            dialog_message=(
                "Could not check GitHub for a new version (API and web fallback both failed).\n\n"
                "Reason: REST API quota exhausted (about 60 requests/hour per egress IP without a "
                "token). Shared office networks, proxies, or repeated startup checks can use the "
                "quota immediately after the reset time shown.\n\n"
                "You can:\n"
                f"{_bullet_retry(when, 'en')}\n"
                "• Add a GitHub token under Tools → Settings (about 5000 requests/hour, recommended)\n"
                "• Disable check-on-startup and avoid hammering Check for Updates while testing"
            ),
        )
    if code == "token_invalid":
        return UpdateCheckFailureText(
            log_line="Update check failed: GitHub token invalid or expired",
            dialog_message=(
                "Could not check GitHub for a new version.\n\n"
                "Reason: the saved token was rejected (401).\n\n"
                "Update or clear the token under Tools → Settings. "
                "For public releases only, clear the token and retry after the rate limit resets."
            ),
        )
    if code == "repo_not_found":
        return UpdateCheckFailureText(
            log_line=f"Update check failed: repository not found ({repo})",
            dialog_message=(
                f"Could not check for updates.\n\n"
                f"Repository «{repo}» was not found (404).\n\n"
                "Set github.repo in config.yaml to a valid owner/name "
                "(e.g. wakaliu/gitbranchtool)."
            ),
        )
    if code == "repo_forbidden":
        return UpdateCheckFailureText(
            log_line=f"Update check failed: no permission for {repo} releases",
            dialog_message=(
                f"Could not check for updates.\n\n"
                f"Access to releases in «{repo}» was denied (403).\n\n"
                "For a private repository, add a token with read access under Tools → Settings."
            ),
        )
    if code == "invalid_repo_config":
        hint = github_repo_config_hint("en")
        return UpdateCheckFailureText(
            log_line="Update check failed: invalid github.repo",
            dialog_message=f"Could not check for updates.\n\n{hint}",
        )
    if code == "timeout":
        return UpdateCheckFailureText(
            log_line="Update check failed: timed out connecting to GitHub",
            dialog_message=(
                "Could not check GitHub for a new version.\n\n"
                "The connection timed out. Check your network or proxy and retry."
            ),
        )
    if code == "network":
        extra = f"\n\nDetails: {detail}" if detail else ""
        return UpdateCheckFailureText(
            log_line="Update check failed: could not connect to GitHub",
            dialog_message=(
                "Could not check GitHub for a new version.\n\n"
                "A network or proxy error occurred."
                f"{extra}\n\n"
                "Ensure github.com is reachable, then retry."
            ),
        )
    if code == "unsupported_platform":
        return UpdateCheckFailureText(
            log_line="Update check failed: platform not supported",
            dialog_message="This platform does not support in-app update checks or installation.",
        )
    if code == "invalid_version":
        ver = detail or "?"
        return UpdateCheckFailureText(
            log_line=f"Update check failed: invalid version ({ver})",
            dialog_message=(
                f"Could not check for updates: version «{ver}» is not valid. "
                "Check app.version in your configuration."
            ),
        )
    return UpdateCheckFailureText(
        log_line="Update check failed: unknown error",
        dialog_message=(
            "Could not complete the update check.\n\n"
            f"{detail or 'See logs/app-error.log for details.'}"
        ),
    )
