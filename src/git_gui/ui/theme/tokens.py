"""UI 主题设计 Token。

集中管理双主题颜色、间距、圆角与字号，避免样式散落在组件中难以维护。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    """单个主题的可复用设计令牌。"""

    window_bg: str
    panel_bg: str
    panel_alt_bg: str
    border: str
    text_primary: str
    text_secondary: str
    primary: str
    primary_hover: str
    success: str
    danger: str
    warning: str
    radius_sm: int = 6
    radius_md: int = 8
    radius_lg: int = 10
    spacing_sm: int = 8
    spacing_md: int = 12
    spacing_lg: int = 16
    font_body: int = 12
    font_title: int = 13
    font_headline: int = 18


LIGHT_TOKENS = ThemeTokens(
    window_bg="#EEF3FF",
    panel_bg="#FFFFFF",
    panel_alt_bg="#F3F6FD",
    border="#D6DEF3",
    text_primary="#0F172A",
    text_secondary="#5B6B86",
    primary="#3B5BFF",
    primary_hover="#304AE0",
    success="#0E9F6E",
    danger="#E02424",
    warning="#D97706",
)

DARK_TOKENS = ThemeTokens(
    window_bg="#0B1224",
    panel_bg="#121A30",
    panel_alt_bg="#19233D",
    border="#2E3F66",
    text_primary="#E8EEFF",
    text_secondary="#9DB0DA",
    primary="#5D7CFF",
    primary_hover="#7F97FF",
    success="#22C55E",
    danger="#F87171",
    warning="#F59E0B",
)


def get_theme_tokens(theme_name: str) -> ThemeTokens:
    """根据主题名返回 token，默认浅色主题。"""
    return DARK_TOKENS if theme_name == "dark" else LIGHT_TOKENS
