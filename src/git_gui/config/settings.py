"""配置管理模块。

统一加载 config.yaml，支持热重载、默认值合并和持久化。
所有可变参数 (路径、主题、语言、收藏分支等) 必须通过此类访问。
"""
from __future__ import annotations

from pathlib import Path
import shutil
import yaml
from typing import Any, Dict
from .constants import (
    DEFAULT_LANGUAGE, DEFAULT_THEME, DEFAULT_MAX_CONCURRENT,
    LOG_MAX_LINES, APP_NAME, APP_VERSION, DEFAULT_PROJECTS_DIR
)
from ..utils.runtime_paths import get_config_file_path, get_embedded_assets_dir

class Settings:
    """单例配置管理器。

    为什么使用单例 + yaml：便于全项目统一配置，避免重复加载，
    支持运行时修改并持久化 (例如用户更改主题后立即保存)。
    """
    _instance = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _ensure_user_config_file(self) -> None:
        """首次启动时从 bundle 复制默认 config，保证可写路径上存在 yaml。"""
        path = get_config_file_path()
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        embedded = get_embedded_assets_dir() / "config.embedded.yaml"
        if embedded.exists():
            shutil.copy(embedded, path)

    def _load_config(self) -> None:
        """加载配置文件，合并默认值。"""
        self._ensure_user_config_file()
        self._config = {
            "app": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "language": DEFAULT_LANGUAGE,
                "theme": DEFAULT_THEME,
            },
            "paths": {"recent_projects": [], "default_branch": "develop"},
            "git": {
                "max_concurrent": DEFAULT_MAX_CONCURRENT,
                "fetch_args": ["--no-tags", "-f"],
                "switch_force": True,
                "auto_unlock": True,
                "switch_max_stash_files": 500,
            },
            "ui": {
                "log_max_lines": LOG_MAX_LINES,
                "show_progress": True,
            },
            "favorites": {"branches": ["develop", "main", "master"]},
            "github": {
                "repo": "your-username/git-gui-pull-switch-tool",
                "issues_url": "https://api.github.com/repos/your-username/git-gui-pull-switch-tool/issues"
            }
        }

        config_path = get_config_file_path()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user_config = yaml.safe_load(f) or {}
                    self._merge_config(self._config, user_config)
            except Exception:
                pass  # 配置文件损坏时使用默认值，避免启动失败

    def _merge_config(self, base: Dict, override: Dict) -> None:
        """递归合并配置字典。"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """通过点分隔路径获取配置，例如 'git.max_concurrent'。"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value if value is not None else default

    def set(self, key: str, value: Any) -> bool:
        """设置配置并持久化到文件。"""
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

        try:
            with open(get_config_file_path(), "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, allow_unicode=True, sort_keys=False)
            return True
        except Exception:
            return False

    def save_recent_projects(self, projects: list[str]) -> None:
        """专门保存最近工程列表，保持用户拖拽顺序。"""
        self.set("paths.recent_projects", projects)

    def get_recent_projects(self) -> list[str]:
        return self.get("paths.recent_projects", [])

    def save_last_added_dir(self, directory: str) -> None:
        """记住用户上次添加工程的目录位置。"""
        self.set("paths.last_added_dir", directory)

    def save_last_selected_project(self, project_path: str) -> None:
        """记住用户上次选中的工程路径。"""
        self.set("paths.last_selected_project", project_path)

    def get_last_selected_project(self) -> Path | None:
        """返回上次选中的工程路径（不存在则返回 None）。"""
        value = self.get("paths.last_selected_project")
        if not value:
            return None
        path = Path(value)
        return path if path.exists() else None

    def save_repo_order(self, project_path: str, repo_paths: list[str]) -> None:
        """保存某工程下仓库自定义顺序。"""
        orders = self.get("paths.repo_orders", {})
        if not isinstance(orders, dict):
            orders = {}
        orders[project_path] = repo_paths
        self.set("paths.repo_orders", orders)

    def get_repo_order(self, project_path: str) -> list[str]:
        """读取某工程下仓库自定义顺序。"""
        orders = self.get("paths.repo_orders", {})
        if not isinstance(orders, dict):
            return []
        value = orders.get(project_path, [])
        return value if isinstance(value, list) else []

    def get_last_added_dir(self) -> Path:
        """返回上次添加工程的目录（不存在则逐级回退到上级，直到找到存在的目录）。"""
        last = self.get("paths.last_added_dir")
        if last:
            p = Path(last)
            while p.exists() is False and str(p) != str(p.parent):
                p = p.parent
            if p.exists():
                return p
        return self.get_default_projects_dir()

    def get_default_projects_dir(self) -> Path:
        """返回默认工程目录（用于添加工程对话框初始路径）。"""
        default = self.get("paths.default_projects_dir")
        if default:
            return Path(default)
        return DEFAULT_PROJECTS_DIR

    @property
    def language(self) -> str:
        return self.get("app.language", DEFAULT_LANGUAGE)

    @property
    def theme(self) -> str:
        return self.get("app.theme", DEFAULT_THEME)
