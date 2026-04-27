"""配置管理模块。

统一加载 config.yaml，支持热重载、默认值合并和持久化。
所有可变参数 (路径、主题、语言、收藏分支等) 必须通过此类访问。
"""
from pathlib import Path
import yaml
from typing import Any, Dict
from .constants import (
    DEFAULT_LANGUAGE, DEFAULT_THEME, DEFAULT_MAX_CONCURRENT,
    LOG_MAX_LINES, CONFIG_FILE, APP_NAME, APP_VERSION
)

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

    def _load_config(self) -> None:
        """加载配置文件，合并默认值。"""
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

        config_path = Path(CONFIG_FILE)
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
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, allow_unicode=True, sort_keys=False)
            return True
        except Exception:
            return False

    def save_recent_projects(self, projects: list[str]) -> None:
        """专门保存最近工程列表，保持用户拖拽顺序。"""
        self.set("paths.recent_projects", projects)

    def get_recent_projects(self) -> list[str]:
        return self.get("paths.recent_projects", [])

    @property
    def language(self) -> str:
        return self.get("app.language", DEFAULT_LANGUAGE)

    @property
    def theme(self) -> str:
        return self.get("app.theme", DEFAULT_THEME)
