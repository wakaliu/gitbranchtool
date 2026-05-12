#!/usr/bin/env bash
# 在 macOS 上由 assets/app_icon.png 生成 assets/icon.icns，供 PyInstaller macOS 规格使用。
# 依赖系统自带的 sips 与 iconutil（勿在 Windows 上运行本脚本）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${ROOT}/assets/app_icon.png"
ICONSET="${ROOT}/assets/icon.iconset"
OUT="${ROOT}/assets/icon.icns"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "请在 macOS 上执行: bash scripts/macos_build_icns.sh" >&2
  exit 1
fi
if [[ ! -f "$SRC" ]]; then
  echo "缺少源图: $SRC" >&2
  exit 1
fi

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

sips -z 16 16 "$SRC" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32 "$SRC" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$SRC" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64 "$SRC" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$SRC" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256 "$SRC" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$SRC" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512 "$SRC" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$SRC" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$SRC" --out "$ICONSET/icon_512x512@2x.png" >/dev/null

iconutil -c icns "$ICONSET" -o "$OUT"
rm -rf "$ICONSET"
echo "已生成: $OUT"
