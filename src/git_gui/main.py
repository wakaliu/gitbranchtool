"""应用入口。

创建 QApplication，加载主窗口，设置高 DPI 支持。
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QCoreApplication

from .config.settings import Settings
from .ui.main_window import MainWindow

def main() -> None:
    """程序入口函数。"""
    # 高 DPI 支持 (Windows/macOS 必需)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

    app = QApplication(sys.argv)
    app.setApplicationName("GitPullSwitchTool")
    app.setOrganizationName("SausageDev")

    # 加载设置 (确保 config.yaml 存在)
    settings = Settings()

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
