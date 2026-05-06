"""GitHub Token 等与系统凭据保管库的交互。

明文不应出现在仓库内的 config.yaml 或源码中；由 OS 提供的钥匙串/凭据管理器
加密落盘。应用内仍会在内存中持有 Token 用于请求，无法对抗具备本机调试权限的攻击者。
"""
from __future__ import annotations

from typing import Optional

KEYRING_SERVICE_NAME = "GitPullSwitchTool"
KEYRING_GITHUB_TOKEN_USER = "github_api_token"


def _keyring_module():
    try:
        import keyring  # type: ignore[import-untyped]
        return keyring
    except ImportError:
        return None


def is_keyring_available() -> bool:
    """本机是否已安装 keyring 且存在可用后端（多数桌面系统默认有）。"""
    kr = _keyring_module()
    if kr is None:
        return False
    try:
        return bool(kr.get_keyring())
    except Exception:
        return False


def get_github_token() -> Optional[str]:
    """从系统凭据库读取 GitHub Token；失败或未配置时返回 None。"""
    kr = _keyring_module()
    if kr is None:
        return None
    try:
        value = kr.get_password(KEYRING_SERVICE_NAME, KEYRING_GITHUB_TOKEN_USER)
        return value.strip() if value else None
    except Exception:
        return None


def set_github_token(token: str) -> bool:
    """将 Token 写入系统凭据库；由 Windows/macOS 等按平台策略保护。"""
    kr = _keyring_module()
    if kr is None:
        return False
    try:
        kr.set_password(KEYRING_SERVICE_NAME, KEYRING_GITHUB_TOKEN_USER, token.strip())
        return True
    except Exception:
        return False


def delete_github_token() -> bool:
    """删除凭据库中的 Token；忽略不存在等情况。"""
    kr = _keyring_module()
    if kr is None:
        return False
    try:
        kr.delete_password(KEYRING_SERVICE_NAME, KEYRING_GITHUB_TOKEN_USER)
        return True
    except Exception:
        return False
