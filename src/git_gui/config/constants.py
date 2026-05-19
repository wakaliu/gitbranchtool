"""常量定义。

所有硬编码字符串和默认值集中在此，避免散落在各处。
配置优先于此处默认值。
"""
from pathlib import Path
from typing import Final

# 应用信息
APP_NAME: Final[str] = "Git 拉线切线工具"
APP_VERSION: Final[str] = "1.0.3"
ORGANIZATION: Final[str] = "SausageDev"

# 支持的语言
SUPPORTED_LANGUAGES: Final[list[str]] = ["zh", "en"]
DEFAULT_LANGUAGE: Final[str] = "zh"

# 主题
SUPPORTED_THEMES: Final[list[str]] = ["light", "dark"]
DEFAULT_THEME: Final[str] = "light"

# Git 相关
DEFAULT_MAX_CONCURRENT: Final[int] = 6
GIT_LOCK_FILES: Final[list[str]] = [".git/index.lock", ".git/HEAD.lock"]

# UI 常量
LOG_MAX_LINES: Final[int] = 500
WINDOW_MIN_SIZE: Final[tuple[int, int]] = (1200, 800)

# 路径
# 运行时配置路径由 utils.runtime_paths.get_config_file_path() 提供（支持 PyInstaller 与开发目录）。
DEFAULT_PROJECTS_DIR: Final[Path] = Path.home() / "Projects"
