"""从 pyproject.toml 同步版本号到代码与打包配置。

发版前在仓库根目录执行: python scripts/sync_version.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def read_pyproject_version(project_root: Path) -> str:
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("pyproject.toml 中未找到 version = \"...\"")
    return match.group(1)


def _replace_pattern(path: Path, pattern: str, repl: str, *, count: int = 1) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(pattern, repl, text, count=count)
    if n == 0:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def sync_version(project_root: Path) -> str:
    version = read_pyproject_version(project_root)
    constants = project_root / "src" / "git_gui" / "config" / "constants.py"
    embedded = project_root / "src" / "git_gui" / "bundle_data" / "config.embedded.yaml"
    iss = project_root / "packaging" / "windows" / "GitPullSwitchTool.iss"

    if not _replace_pattern(
        constants,
        r'APP_VERSION: Final\[str\] = "[^"]+"',
        f'APP_VERSION: Final[str] = "{version}"',
    ):
        raise SystemExit(f"未能更新 {constants}")

    if not _replace_pattern(
        embedded,
        r"(\n  version: )[^\n]+",
        rf"\g<1>{version}",
    ):
        raise SystemExit(f"未能更新 {embedded}")

    if not _replace_pattern(
        iss,
        r'#define MyAppVersion "[^"]+"',
        f'#define MyAppVersion "{version}"',
    ):
        raise SystemExit(f"未能更新 {iss}")

    return version


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    version = sync_version(root)
    print(f"Synced version {version} to constants, embedded config, and Inno Setup script.")


if __name__ == "__main__":
    main()
    sys.exit(0)
