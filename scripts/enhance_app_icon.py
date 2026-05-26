"""将 app_icon.png 裁切、放大至画幅占比、提亮笔画并锐化，改善任务栏小图标糊感。

小尺寸 ICO 会二次抽样，源图字重占画幅比过低时必然发糊；本脚本在打包前对 PNG 做一次
确定性增强，避免依赖模型再次出图。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def _premultiply_rgba(im: Image.Image) -> Image.Image:
    """与 compose 脚本一致：预乘后再缩放，减轻半透明边在缩小后的发灰、发糊。"""
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
    """将预乘域像素还原为常规 RGBA（与 _premultiply_rgba 配对使用）。"""
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


def _dist2(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _brighten_foreground(im: Image.Image, bg: tuple[int, int, int], *, thr: int, mult: float) -> Image.Image:
    """将偏离背景的像素按 mult 提亮（封顶 255），背景保持不变。"""
    px = im.load()
    w, h = im.size
    out = im.copy()
    opx = out.load()
    thr2 = thr * thr
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            if _dist2((r, g, b), bg) < thr2:
                continue
            opx[x, y] = (
                min(255, int(r * mult)),
                min(255, int(g * mult)),
                min(255, int(b * mult)),
                a,
            )
    return out


def _apply_rounded_corners(im: Image.Image, radius: int) -> Image.Image:
    """按圆角矩形裁切画布，四角透明，便于 exe / 任务栏呈现现代圆角图标。"""
    if radius <= 0:
        return im.convert("RGBA")
    im = im.convert("RGBA")
    w, h = im.size
    radius = min(radius, w // 2, h // 2)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def render_enhanced_icon(
    src: Path,
    *,
    canvas: int,
    fill_ratio: float,
    brighten: float,
    bg_rgb: tuple[int, int, int],
    corner_radius_ratio: float,
) -> Image.Image:
    im = Image.open(src).convert("RGBA")
    bbox = im.getbbox()
    if not bbox:
        raise SystemExit("源图无可见内容")
    im = im.crop(bbox)
    tw = int(canvas * fill_ratio)
    th = int(canvas * fill_ratio)
    scale = min(tw / im.width, th / im.height)
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    supersample = 5
    pm = _premultiply_rgba(im)
    big = pm.resize((nw * supersample, nh * supersample), Image.Resampling.LANCZOS)
    down = getattr(Image.Resampling, "BOX", Image.Resampling.LANCZOS)
    sharp = big.resize((nw, nh), down)
    sharp = _demultiply_rgba(sharp)
    sharp = sharp.filter(ImageFilter.UnsharpMask(radius=0.72, percent=92, threshold=5))

    canvas_img = Image.new("RGBA", (canvas, canvas), (*bg_rgb, 255))
    x = (canvas - nw) // 2
    y = (canvas - nh) // 2
    canvas_img.paste(sharp, (x, y), sharp)

    canvas_img = _brighten_foreground(canvas_img, bg_rgb, thr=28, mult=brighten)
    canvas_img = canvas_img.filter(ImageFilter.UnsharpMask(radius=0.55, percent=58, threshold=3))
    corner_radius = int(canvas * corner_radius_ratio)
    return _apply_rounded_corners(canvas_img, corner_radius)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Enhance app_icon for sharper/brighter/larger glyphs.")
    parser.add_argument("--src", type=Path, default=root / "assets" / "app_icon.png")
    parser.add_argument("--out-png", type=Path, default=root / "assets" / "app_icon.png")
    parser.add_argument("--out-ico", type=Path, default=root / "assets" / "icon.ico")
    parser.add_argument("--bundle-png", type=Path, default=root / "src" / "git_gui" / "bundle_data" / "app_icon.png")
    parser.add_argument("--canvas", type=int, default=1024)
    parser.add_argument("--fill-ratio", type=float, default=0.97, help="字形最大边占画布比例")
    parser.add_argument(
        "--brighten",
        type=float,
        default=1.08,
        help="前景 RGB 乘子（合成已为青绿实色时不宜过大，易糊边）",
    )
    parser.add_argument("--bg-r", type=int, default=11)
    parser.add_argument("--bg-g", type=int, default=18)
    parser.add_argument("--bg-b", type=int, default=32)
    parser.add_argument(
        "--corner-radius-ratio",
        type=float,
        default=0.20,
        help="圆角半径占画布边长比例（0 关闭；默认 0.20 接近 macOS / Win11 应用图标观感）",
    )
    args = parser.parse_args()
    bg = (args.bg_r, args.bg_g, args.bg_b)
    img = render_enhanced_icon(
        args.src,
        canvas=args.canvas,
        fill_ratio=args.fill_ratio,
        brighten=args.brighten,
        bg_rgb=bg,
        corner_radius_ratio=args.corner_radius_ratio,
    )
    args.out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out_png, format="PNG", optimize=True)
    img.save(
        args.out_ico,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)],
    )
    shutil.copyfile(args.out_png, args.bundle_png)
    print(f"Wrote {args.out_png}, {args.out_ico}, {args.bundle_png}")


if __name__ == "__main__":
    main()
