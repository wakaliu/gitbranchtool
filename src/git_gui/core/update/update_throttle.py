"""更新检查的启动冷却与 GitHub 限流退避（持久化到 config，减少无效 API 请求）。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ...config.settings import Settings
from .check_messages import UpdateCheckFailureText, format_update_check_failure


@dataclass(frozen=True)
class UpdateCheckGate:
    """是否允许发起一次 GitHub 检查。"""

    allowed: bool
    silent: bool
    failure: Optional[UpdateCheckFailureText] = None


def _now() -> float:
    return time.time()


def _format_reset_hint(unix_ts: float, language: str) -> str:
    if unix_ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(unix_ts).strftime("%H:%M")
    except (ValueError, OSError):
        return ""


def get_rate_limit_backoff_until(settings: Settings) -> float:
    """限流退避截止时间（Unix 秒），0 表示未处于退避期。"""
    return float(settings.get("update.rate_limit_backoff_until", 0) or 0)


def get_last_auto_check_at(settings: Settings) -> float:
    """上次启动自动检查实际访问 API 的时间（Unix 秒）；手动检查不计入。"""
    auto_at = float(settings.get("update.last_auto_check_at", 0) or 0)
    if auto_at > 0:
        return auto_at
    # 兼容旧版误写入 last_check_at 的字段，仅在没有新字段时回退
    return float(settings.get("update.last_check_at", 0) or 0)


def record_auto_check_attempt(settings: Settings) -> None:
    """记录一次启动自动检查（手动「检查更新」不调用）。"""
    settings.set("update.last_auto_check_at", _now())


def record_rate_limit_backoff(settings: Settings, reset_unix: int = 0) -> None:
    """命中限流后写入退避截止时间，优先使用 GitHub 的 Reset 时刻。"""
    now = _now()
    if reset_unix > now:
        until = float(reset_unix) + 30
    else:
        fallback_min = max(1, int(settings.get("update.rate_limit_fallback_minutes", 60) or 60))
        until = now + fallback_min * 60
    settings.set("update.rate_limit_backoff_until", until)


def clear_rate_limit_backoff(settings: Settings) -> None:
    """检查成功后清除退避，避免长期误跳过。"""
    settings.set("update.rate_limit_backoff_until", 0)


def evaluate_update_check_gate(settings: Settings, *, auto: bool) -> UpdateCheckGate:
    """在发起网络请求前判断是否应跳过检查。

    Args:
        settings: 配置单例。
        auto: 是否为启动自动检查（仅自动检查应用启动冷却）。

    Returns:
        ``UpdateCheckGate``：不允许时 ``failure`` 供手动检查弹窗/日志使用。
    """
    language = str(settings.get("app.language", "zh") or "zh")
    now = _now()
    backoff_until = get_rate_limit_backoff_until(settings)
    if backoff_until > now:
        reset_hint = _format_reset_hint(backoff_until, language)
        failure = format_update_check_failure(
            language, "rate_limit", reset_time=reset_hint
        )
        return UpdateCheckGate(allowed=False, silent=auto, failure=failure)

    if auto:
        cooldown_min = max(
            0, int(settings.get("update.startup_check_cooldown_minutes", 30) or 30)
        )
        if cooldown_min > 0:
            last = get_last_auto_check_at(settings)
            if last > 0 and now - last < cooldown_min * 60:
                return UpdateCheckGate(allowed=False, silent=True, failure=None)

    return UpdateCheckGate(allowed=True, silent=False, failure=None)


def rate_limit_backoff_reset_hint(settings: Settings, language: str = "zh") -> str:
    """退避期结束时对应的本地时间提示（HH:MM）。"""
    return _format_reset_hint(get_rate_limit_backoff_until(settings), language)


def startup_check_cooldown_minutes(settings: Settings) -> int:
    """配置的启动自动检查冷却时长（分钟）。"""
    return max(0, int(settings.get("update.startup_check_cooldown_minutes", 30) or 30))


def startup_cooldown_remaining_seconds(settings: Settings) -> int:
    """距允许下次启动自动检查还剩多少秒。"""
    cooldown_min = startup_check_cooldown_minutes(settings)
    if cooldown_min <= 0:
        return 0
    last = get_last_auto_check_at(settings)
    if last <= 0:
        return 0
    remain_sec = int(cooldown_min * 60 - (_now() - last))
    return max(0, remain_sec)
