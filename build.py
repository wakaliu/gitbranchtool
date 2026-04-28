"""打包脚本。

使用 PyInstaller 将应用打包为单文件可执行程序。
支持 Windows .exe 和 macOS Universal2 .app。
"""
import sys
from pathlib import Path
import subprocess

def build_windows():
    """打包 Windows 版本。"""
    print("正在打包 Windows 版本...")
    cmd = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        "--name", "GitPullSwitchTool",
        "--icon", "assets/icon.ico" if Path("assets/icon.ico").exists() else None,
        "--add-data", "config.yaml;.",
        "src/git_gui/main.py"
    ]
    # 过滤 None
    cmd = [x for x in cmd if x is not None]
    subprocess.run(cmd, check=True)
    print("Windows 打包完成！可执行文件在 dist/ 目录")

def build_macos():
    """打包 macOS Universal2 版本。"""
    print("正在打包 macOS Universal2 版本...")
    cmd = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        "--name", "GitPullSwitchTool",
        "--target-arch", "universal2",
        "--add-data", "config.yaml:.",
        "src/git_gui/main.py"
    ]
    subprocess.run(cmd, check=True)
    print("macOS 打包完成！可执行文件在 dist/ 目录")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mac":
        build_macos()
    else:
        build_windows()
    print("\n打包完成！请将 config.yaml 复制到可执行文件同目录。")
