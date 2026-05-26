"""检查更新失败时的错误码，供 i18n 文案映射。"""
from __future__ import annotations

from typing import Any


class UpdateCheckError(Exception):
    """携带 ``code`` 与上下文字段，由 ``check_for_update_safe`` 转为界面文案。"""

    def __init__(self, code: str, **context: Any) -> None:
        self.code = code
        self.context = context
        super().__init__(code)
