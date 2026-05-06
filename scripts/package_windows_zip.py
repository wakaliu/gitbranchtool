"""将 Windows 便携版 exe 与说明文件打成 zip，供 Release 附带下载。

默认从 pyproject.toml 读取版本号；CI 可通过 --version 传入 tag（如 v1.0.2）。
"""
from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path

README_LINES = [
    "Git 拉线切线工具（Windows 便携版）",
    "",
    "1. 解压后双击 GitPullSwitchTool.exe 运行。",
    "2. 本机需已安装 Git，并可在命令行执行 git。",
    "3. 首次运行配置写入 %LOCALAPPDATA%\\GitPullSwitchTool\\config.yaml。",
    "4. 更新与反馈：见 GitHub 仓库 Releases。",
]


def read_pyproject_version(project_root: Path) -> str:
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Windows portable exe into a release zip.")
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path("dist"),
        help="Directory containing GitPullSwitchTool.exe",
    )
    parser.add_argument(
        "--exe-name",
        default="GitPullSwitchTool.exe",
        help="Portable executable file name",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Override version label in zip file name (e.g. v1.0.2 from CI tag)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    dist_dir = args.dist_dir if args.dist_dir.is_absolute() else project_root / args.dist_dir
    exe_path = dist_dir / args.exe_name
    if not exe_path.is_file():
        raise SystemExit(f"未找到便携版程序: {exe_path}")

    ver = (args.version or "").strip() or read_pyproject_version(project_root)
    if not ver.startswith("v"):
        ver_label = f"v{ver}"
    else:
        ver_label = ver

    zip_name = f"GitPullSwitchTool-Windows-{ver_label}.zip"
    zip_path = dist_dir / zip_name

    readme_name = "使用说明-Windows.txt"
    readme_body = "\r\n".join(README_LINES) + "\r\n"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, arcname=args.exe_name)
        zf.writestr(readme_name, readme_body.encode("utf-8"))

    print(f"已生成: {zip_path}")


if __name__ == "__main__":
    main()
