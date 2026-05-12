"""从「切线」横向参考图裁出两字，仅做缩放与排版，不改篆书写法。

上一版用扩散模型重绘会改变笔画结构；本脚本只使用用户提供的 PNG 像素，
将左字放大、右字缩小置于右下角，再铺实色底，便于与 enhance_app_icon 衔接。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter


def _luma(r: int, g: int, b: int) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def _corner_mean_luma(im: Image.Image) -> float:
    px = im.load()
    w, h = im.size
    pts = [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)]
    return sum(_luma(*px[x, y][:3]) for x, y in pts) / len(pts)


def _is_fg(p: tuple[int, int, int, int], bg_dark: bool, margin: float) -> bool:
    r, g, b, a = p
    if a < 40:
        return False
    lum = _luma(r, g, b)
    return lum > margin if bg_dark else lum < (255 - margin)


def _bbox_foreground(im: Image.Image, bg_dark: bool, margin: float) -> tuple[int, int, int, int] | None:
    px = im.load()
    w, h = im.size
    min_x, min_y, max_x, max_y = w, h, 0, 0
    found = False
    for y in range(h):
        for x in range(w):
            if _is_fg(px[x, y], bg_dark, margin):
                found = True
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if not found:
        return None
    return min_x, min_y, max_x + 1, max_y + 1


def _column_fg_counts(im: Image.Image, bg_dark: bool, margin: float) -> list[int]:
    g = im.convert("RGBA")
    px = g.load()
    w, h = g.size
    counts = []
    for x in range(w):
        c = 0
        for y in range(h):
            if _is_fg(px[x, y], bg_dark, margin):
                c += 1
        counts.append(c)
    return counts


def _split_x(im: Image.Image, bg_dark: bool, margin: float) -> int:
    """在横向投影低谷处分两字，避免硬切笔画。"""
    w, _ = im.size
    cols = _column_fg_counts(im, bg_dark, margin)
    lo, hi = int(w * 0.22), int(w * 0.78)
    if hi <= lo + 4:
        return w // 2
    best = min(range(lo, hi), key=lambda x: cols[x])
    return int(best)


def _resize_h(im: Image.Image, target_h: int) -> Image.Image:
    if target_h <= 0 or im.height <= 0:
        return im
    ratio = target_h / im.height
    nw = max(1, int(im.width * ratio))
    nh = max(1, int(im.height * ratio))
    big = im.resize((nw * 2, nh * 2), Image.Resampling.LANCZOS)
    return big.resize((nw, nh), Image.Resampling.LANCZOS)


def compose(
    ref: Path,
    out: Path,
    *,
    canvas: int,
    bg: tuple[int, int, int],
    left_h_ratio: float,
    right_h_ratio: float,
    margin: int,
    fg_margin: float,
) -> Image.Image:
    im = Image.open(ref).convert("RGBA")
    bg_dark = _corner_mean_luma(im) < 90
    bx = _bbox_foreground(im, bg_dark, fg_margin)
    if not bx:
        raise SystemExit("参考图中未检测到前景笔画")
    im = im.crop(bx)
    split = _split_x(im, bg_dark, fg_margin)
    w = im.width
    left = im.crop((0, 0, split, im.height))
    right = im.crop((split, 0, w, im.height))
    lb = _bbox_foreground(left, bg_dark, fg_margin)
    rb = _bbox_foreground(right, bg_dark, fg_margin)
    if not lb or not rb:
        raise SystemExit("左右字裁切失败")
    left = left.crop(lb)
    right = right.crop(rb)

    target_left_h = int(canvas * left_h_ratio)
    target_right_h = int(target_left_h * right_h_ratio)
    left_r = _resize_h(left, target_left_h).filter(ImageFilter.UnsharpMask(radius=0.9, percent=120, threshold=2))
    right_r = _resize_h(right, target_right_h).filter(ImageFilter.UnsharpMask(radius=0.8, percent=110, threshold=2))

    canvas_img = Image.new("RGBA", (canvas, canvas), (*bg, 255))
    lx = margin
    ly = (canvas - left_r.height) // 2
    canvas_img.paste(left_r, (lx, ly), left_r)

    rx = canvas - margin - right_r.width
    ry = canvas - margin - right_r.height
    canvas_img.paste(right_r, (rx, ry), right_r)

    return canvas_img


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Compose asymmetric icon from reference 切线 PNG without redrawing glyphs.")
    p.add_argument("--ref", type=Path, default=root / "assets" / "reference_qiexian_seal.png")
    p.add_argument("--out", type=Path, default=root / "assets" / "app_icon.png")
    p.add_argument("--canvas", type=int, default=1024)
    p.add_argument("--margin", type=int, default=28)
    p.add_argument("--left-h-ratio", type=float, default=0.82, help="左字高度占画布比例")
    p.add_argument("--right-h-ratio", type=float, default=0.30, help="右字相对左字高度比例")
    p.add_argument("--bg-r", type=int, default=11)
    p.add_argument("--bg-g", type=int, default=18)
    p.add_argument("--bg-b", type=int, default=32)
    p.add_argument("--fg-margin", type=float, default=88.0, help="前景/背景分界亮度阈值")
    args = p.parse_args()
    bg = (args.bg_r, args.bg_g, args.bg_b)
    img = compose(
        args.ref,
        args.out,
        canvas=args.canvas,
        bg=bg,
        left_h_ratio=args.left_h_ratio,
        right_h_ratio=args.right_h_ratio,
        margin=args.margin,
        fg_margin=args.fg_margin,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, format="PNG", optimize=True)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
