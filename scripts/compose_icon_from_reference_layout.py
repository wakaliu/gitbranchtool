"""从「切线」横向参考图裁出两字，仅做缩放与排版，不改篆书写法。

上一版用扩散模型重绘会改变笔画结构；本脚本只使用用户提供的 PNG 像素，
将左字放大、右字缩小，两字底对齐、横向紧凑排列，再整体等比缩放至撑满画布（留少量边距），
最后铺实色底，便于与 enhance_app_icon 衔接。

字形发糊的常见原因：参考图笔画外圈多为宽过渡（霓虹/抗锯齿），经 LANCZOS 放大后
过渡带被拉长；ICO 多尺寸再抽样也会软化边缘。本脚本通过抽实色+压薄弱 alpha、
大字更高倍超采样减轻上述效应。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageFilter

# 前景统一为白色（与纯黑底强对比）；RGB 为实色，透明度由原图亮度承担以保留边缘抗锯齿。
FG_RGB = (255, 255, 255)


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


def _glyph_to_teal_layer(im: Image.Image, bg_dark: bool, fg_margin: float, rgb: tuple[int, int, int] = FG_RGB) -> Image.Image:
    """把参考图里的亮笔画抽成「实色 + 透明度」，去掉原图霓虹底/浅蓝块，避免贴到画布上出现矩形色差。"""
    w, h = im.size
    px = im.convert("RGBA").load()
    fr, fg, fb = rgb
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    opx = out.load()
    for yy in range(h):
        for xx in range(w):
            r, g, b, a = px[xx, yy]
            if a < 42:
                continue
            lum = _luma(r, g, b)
            if bg_dark and lum <= fg_margin - 8:
                continue
            if not bg_dark and lum >= 255 - fg_margin:
                continue
            strength = max(r, g, b) / 255.0 if bg_dark else (255 - min(r, g, b)) / 255.0
            strength = max(0.0, min(1.0, strength * 1.1 - 0.02))
            # 参考图霓虹外圈多为半透明宽过渡，直接缩放会把过渡带拉成「糊边」；压暗弱通道保留抗锯齿芯部。
            strength = min(1.0, strength ** 1.28)
            alpha = int(a * strength)
            if alpha < 10:
                continue
            opx[xx, yy] = (fr, fg, fb, alpha)
    bb = out.getbbox()
    if not bb:
        raise SystemExit("抽前景失败：请检查 --fg-margin 或参考图对比度")
    return out.crop(bb)


def _premultiply_rgba(im: Image.Image) -> Image.Image:
    """将 RGB 按 alpha 预乘，便于后续缩放时把半透明边当作「颜色+不透明度」插值，减轻青字周围的灰/青假边。"""
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ox = out.load()
    for yy in range(h):
        for xx in range(w):
            r, g, b, a = px[xx, yy]
            if a == 0:
                continue
            f = a / 255.0
            ox[xx, yy] = (int(r * f + 0.5), int(g * f + 0.5), int(b * f + 0.5), a)
    return out


def _demultiply_rgba(im: Image.Image) -> Image.Image:
    """将预乘域像素还原为常规 RGBA，避免笔画芯部发灰（与 _premultiply_rgba 配对）。"""
    px = im.load()
    w, h = im.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ox = out.load()
    for yy in range(h):
        for xx in range(w):
            pr, pg, pb, pa = px[xx, yy]
            if pa <= 0:
                continue
            s = 255.0 / float(pa)
            r = min(255, int(pr * s + 0.5))
            g = min(255, int(pg * s + 0.5))
            b = min(255, int(pb * s + 0.5))
            ox[xx, yy] = (r, g, b, pa)
    return out


def _narrow_alpha_fringe(im: Image.Image, *, lo: int = 40, hi: int = 200) -> Image.Image:
    """压窄半透明过渡带宽度，使笔画与底色交界更利落；lo/hi 过小会产生锯齿，需在清晰度与锯齿间折中。"""
    r, g, b, a = im.split()

    def _map_a(p: int) -> int:
        if p <= lo:
            return 0
        if p >= hi:
            return 255
        return int((p - lo) / (hi - lo) * 255)

    a2 = a.point(_map_a)
    return Image.merge("RGBA", (r, g, b, a2))


def _alpha_maxfilter(im: Image.Image, size: int = 3) -> Image.Image:
    """对 alpha 做极小邻域膨胀，笔画略加粗更饱满；仅动 alpha，不改笔画实色。"""
    r, g, b, a = im.split()
    a2 = a.filter(ImageFilter.MaxFilter(size))
    return Image.merge("RGBA", (r, g, b, a2))


def _suppress_alpha_spatter(im: Image.Image, *, min_alpha: int = 28) -> Image.Image:
    """去掉缩放与反预乘后残留的极低 alpha 像素，避免非笔画处出现青绿色碎点/斑块。"""
    r, g, b, a = im.split()

    def _clip(p: int) -> int:
        return 0 if p < min_alpha else p

    a2 = a.point(_clip)
    return Image.merge("RGBA", (r, g, b, a2))


def _resize_to_wh(im: Image.Image, nw: int, nh: int, *, oversample: int = 6) -> Image.Image:
    """在预乘 alpha 域做超采样缩放，再还原；最终缩小优先 BOX，减轻笔画缩小后的糊感与假边。"""
    if nw < 1 or nh < 1 or im.width < 1 or im.height < 1:
        return im
    k = max(2, oversample)
    pm = _premultiply_rgba(im)
    big = pm.resize((nw * k, nh * k), Image.Resampling.LANCZOS)
    down = getattr(Image.Resampling, "BOX", Image.Resampling.LANCZOS)
    sm = big.resize((nw, nh), down)
    return _demultiply_rgba(sm)


def _resize_h(im: Image.Image, target_h: int, *, oversample: int = 5) -> Image.Image:
    if target_h <= 0 or im.height <= 0:
        return im
    ratio = target_h / im.height
    nw = max(1, int(im.width * ratio))
    nh = max(1, int(im.height * ratio))
    return _resize_to_wh(im, nw, nh, oversample=oversample)


def compose(
    ref: Path,
    out: Path,
    *,
    canvas: int,
    bg: tuple[int, int, int],
    left_h_ratio: float,
    right_h_ratio: float,
    fill_pad: int,
    glyph_gap: int,
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

    left = _glyph_to_teal_layer(left, bg_dark, fg_margin)
    right = _glyph_to_teal_layer(right, bg_dark, fg_margin)

    target_left_h = int(canvas * left_h_ratio)
    target_right_h = int(target_left_h * right_h_ratio)
    left_r = _resize_h(left, target_left_h, oversample=6)
    right_r = _resize_h(right, target_right_h, oversample=4)

    tw = left_r.width + glyph_gap + right_r.width
    th = max(left_r.height, right_r.height)
    strip = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    strip.paste(left_r, (0, th - left_r.height), left_r)
    strip.paste(right_r, (left_r.width + glyph_gap, th - right_r.height), right_r)

    bb = strip.getbbox()
    if not bb:
        raise SystemExit("排字后无可见前景")
    patch = strip.crop(bb)
    inner = max(1, canvas - 2 * fill_pad)
    sc = min(inner / patch.width, inner / patch.height)
    nw, nh = max(1, int(round(patch.width * sc))), max(1, int(round(patch.height * sc)))
    fitted = _resize_to_wh(patch, nw, nh, oversample=7)
    fitted = _narrow_alpha_fringe(fitted, lo=32, hi=218)
    fitted = _suppress_alpha_spatter(fitted, min_alpha=24)
    fitted = _alpha_maxfilter(fitted, size=5)
    canvas_img = Image.new("RGBA", (canvas, canvas), (*bg, 255))
    canvas_img.paste(fitted, ((canvas - nw) // 2, (canvas - nh) // 2), fitted)
    return canvas_img


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Compose asymmetric icon from reference 切线 PNG without redrawing glyphs.")
    p.add_argument("--ref", type=Path, default=root / "assets" / "reference_qiexian_seal.png")
    p.add_argument("--out", type=Path, default=root / "assets" / "app_icon.png")
    p.add_argument("--canvas", type=int, default=1024)
    p.add_argument(
        "--fill-pad",
        type=int,
        default=2,
        help="字形整体距画布边缘留白（像素）；越小越撑满",
    )
    p.add_argument("--glyph-gap", type=int, default=4, help="两字之间的横向间距（像素）")
    p.add_argument(
        "--left-h-ratio",
        type=float,
        default=0.98,
        help="左字初始高度占画布比例；整体会再缩放撑满，通常取 0.96–0.99",
    )
    p.add_argument("--right-h-ratio", type=float, default=0.40, help="右字相对左字高度比例")
    p.add_argument("--bg-r", type=int, default=0)
    p.add_argument("--bg-g", type=int, default=0)
    p.add_argument("--bg-b", type=int, default=0)
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
        fill_pad=args.fill_pad,
        glyph_gap=args.glyph_gap,
        fg_margin=args.fg_margin,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out, format="PNG", optimize=True)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
