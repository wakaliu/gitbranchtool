#!/usr/bin/env python3
"""生成 DMG 资源：纯色背景 + 透明提示图（作 Finder 自定义图标，无文件预览框）。"""
from __future__ import annotations

import sys
from pathlib import Path

WIN_W = 660
WIN_H = 430
ICON_SIZE = 128
APP_X, APP_Y = 160, 180
APPS_X, APPS_Y = 480, 180
SCALE = 2

ARROW_COLOR = "#FF5A1F"
BG_COLOR = "#ECECF0"


def hint_icon_pos() -> tuple[int, int]:
    """与 make_dmg.sh 中 --add-file 坐标一致。"""
    gap_left = APP_X + ICON_SIZE
    gap_right = APPS_X
    x = gap_left + (gap_right - gap_left - ICON_SIZE) // 2
    return x, APP_Y


def _draw_arrow(p: object, x1: float, y1: float, x2: float, y2: float) -> None:
    """橙色箭身 + 箭头，箭头接在杆右侧、不遮挡杆。"""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainterPath, QPen, QPolygonF

    line_w = 58
    head_w, head_h = 200, 96
    shaft_end = x2 - head_w
    orange = QColor(ARROW_COLOR)

    pen = QPen(orange)
    pen.setWidth(line_w)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.drawLine(int(x1), int(y1), int(shaft_end), int(y2))

    head = QPolygonF(
        [
            QPointF(x2, y2),
            QPointF(shaft_end, y2 - head_h),
            QPointF(shaft_end, y2 + head_h),
        ]
    )
    path = QPainterPath()
    path.addPolygon(head)
    p.setBrush(orange)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawPath(path)


def _clear_alpha_fringe(img: object, max_y: int) -> None:
    """去掉文字/图形上方的半透明像素，避免 Finder 缩放后出现灰影块。"""
    from PySide6.QtGui import QColor

    w = img.width()
    limit = min(max_y, img.height())
    transparent = QColor(0, 0, 0, 0)
    for y in range(limit):
        for x in range(w):
            if img.pixelColor(x, y).alpha() > 0:
                img.setPixelColor(x, y, transparent)


def _trim_and_embed_icon(src: object, size: int = 512) -> object:
    """裁切到实际内容后嵌入正方形画布，顶部留白为全透明。"""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    w, h = src.width(), src.height()
    min_x, min_y, max_x, max_y = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            if src.pixelColor(x, y).alpha() > 20:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if min_x > max_x:
        return src
    pad = 10
    crop = src.copy(
        QRect(
            max(0, min_x - pad),
            max(0, min_y - pad),
            max_x - min_x + 1 + 2 * pad,
            max_y - min_y + 1 + 2 * pad,
        )
    )
    out = QImage(size, size, QImage.Format.Format_ARGB32)
    out.fill(0)
    margin = 2
    scale = min((size - margin) / crop.width(), (size - margin) / crop.height())
    tw = int(crop.width() * scale)
    th = int(crop.height() * scale)
    scaled = crop.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    ox = (size - tw) // 2
    oy = (size - th) // 2
    p = QPainter(out)
    p.drawImage(ox, oy, scaled)
    p.end()
    return out


def _paint_plain_background(img: object) -> None:
    from PySide6.QtGui import QColor, QPainter

    p = QPainter(img)
    p.fillRect(0, 0, img.width(), img.height(), QColor(BG_COLOR))
    p.end()


def _paint_hint_icon(img: object) -> None:
    """透明底，仅文字 + 大箭头（用作自定义图标，避免 Finder 预览白框）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter

    w = img.width()
    h = img.height()
    arrow_y = h * 0.66
    arrow_x1 = w * 0.01
    arrow_x2 = w * 0.99
    text_h = 96
    # 箭头三角高度 96 + 杆半宽，文字底边须在其上方留空
    arrow_head_h = 96
    arrow_line_w = 58
    text_gap = arrow_head_h + arrow_line_w // 2 + 20
    text_top = arrow_y - text_gap - text_h

    img.fill(0)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    title_font = QFont()
    title_font.setPixelSize(76)
    title_font.setBold(True)
    title_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    p.setFont(title_font)
    p.setPen(QColor("#1D1D1F"))
    p.setBackgroundMode(Qt.BGMode.TransparentMode)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawText(0, int(text_top), w, text_h, Qt.AlignmentFlag.AlignHCenter, "拖到应用程序")

    _draw_arrow(p, arrow_x1, arrow_y, arrow_x2, arrow_y)
    p.end()

    _clear_alpha_fringe(img, int(text_top) - 4)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    out_bg = script_dir / "dmg_background.png"
    out_hint = script_dir / "dmg_hint.png"
    if len(sys.argv) > 1:
        out_bg = Path(sys.argv[1]).resolve()
    if len(sys.argv) > 2:
        out_hint = Path(sys.argv[2]).resolve()

    try:
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(f"需要 PySide6: {exc}", file=sys.stderr)
        return 1

    app = QApplication.instance() or QApplication([])

    bg = QImage(WIN_W * SCALE, WIN_H * SCALE, QImage.Format.Format_RGB32)
    _paint_plain_background(bg)
    if not bg.save(str(out_bg), "PNG"):
        print(f"无法写入 {out_bg}", file=sys.stderr)
        return 1

    hint_raw = QImage(768, 768, QImage.Format.Format_ARGB32)
    _paint_hint_icon(hint_raw)
    hint = _trim_and_embed_icon(hint_raw)
    if not hint.save(str(out_hint), "PNG"):
        print(f"无法写入 {out_hint}", file=sys.stderr)
        return 1

    hx, hy = hint_icon_pos()
    print(f"hint_position: {hx}, {hy}", file=sys.stderr)
    del app
    print(out_bg)
    print(out_hint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
