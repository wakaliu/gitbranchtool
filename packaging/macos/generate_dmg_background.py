#!/usr/bin/env python3
"""生成 DMG 窗口背景图（2x），提示将 .app 拖到「应用程序」。"""
from __future__ import annotations

import sys
from pathlib import Path

# 与 make_dmg.sh 中窗口/图标布局一致（逻辑坐标 660×400，输出 2x）
WIDTH = 1320
HEIGHT = 800
APP_ICON_POS = (320, 370)  # 2x of (160, 185)
APPS_ICON_POS = (960, 370)  # 2x of (480, 185)


def main() -> int:
    out = Path(__file__).resolve().parent / "dmg_background.png"
    if len(sys.argv) > 1:
        out = Path(sys.argv[1]).resolve()

    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(f"需要 PySide6 以生成背景图: {exc}", file=sys.stderr)
        return 1

    app = QApplication.instance() or QApplication([])

    img = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB32)
    img.fill(QColor("#f4f4f6"))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 箭头：应用图标右侧 -> 应用程序图标左侧
    x1, y1 = APP_ICON_POS[0] + 110, APP_ICON_POS[1] + 40
    x2, y2 = APPS_ICON_POS[0] - 30, APPS_ICON_POS[1] + 40
    pen = QPen(QColor("#86868b"))
    pen.setWidth(6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(int(x1), int(y1), int(x2), int(y2))
    # 箭头三角
    head = QPolygonF(
        [
            QPointF(x2, y2),
            QPointF(x2 - 28, y2 - 14),
            QPointF(x2 - 28, y2 + 14),
        ]
    )
    p.setBrush(QColor("#86868b"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPolygon(head)

    p.setPen(QColor("#1d1d1f"))
    title_font = QFont()
    title_font.setPixelSize(36)
    title_font.setBold(True)
    p.setFont(title_font)
    p.drawText(0, HEIGHT - 120, WIDTH, 50, Qt.AlignmentFlag.AlignHCenter, "将左侧应用拖到「应用程序」文件夹")
    sub_font = QFont()
    sub_font.setPixelSize(26)
    p.setFont(sub_font)
    p.setPen(QColor("#6e6e73"))
    p.drawText(
        0,
        HEIGHT - 70,
        WIDTH,
        40,
        Qt.AlignmentFlag.AlignHCenter,
        "Drag the app to the Applications folder",
    )
    p.end()

    if not img.save(str(out), "PNG"):
        print(f"无法写入 {out}", file=sys.stderr)
        return 1
    del app
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
