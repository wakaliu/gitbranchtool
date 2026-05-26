#!/usr/bin/env bash
# 从 PyInstaller 生成的 .app 制作只读压缩 DMG（无代码签名）。
# 使用 Finder 别名指向 /Applications；窗口背景图提示拖放安装。
# 用法：
#   ./make_dmg.sh                                    # 默认：GitPullSwitchTool.app -> GitPullSwitchTool.dmg
#   ./make_dmg.sh <App路径> <dmg文件名> [卷标名]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${ROOT}/dist/macos-installer"

APP_SRC="${1:-${ROOT}/dist/macos-portable/GitPullSwitchTool.app}"
DMG_NAME="${2:-GitPullSwitchTool.dmg}"
VOL_NAME="${3:-$(basename "${APP_SRC}" .app)}"

# 与 generate_dmg_background.py / AppleScript 布局一致
WIN_X=400
WIN_Y=100
WIN_W=660
WIN_H=400
ICON_SIZE=80
APP_ICON_X=160
APP_ICON_Y=185
APPS_ICON_X=480
APPS_ICON_Y=185

if [[ ! -d "${APP_SRC}" ]]; then
  echo "缺少 .app：${APP_SRC}" >&2
  echo "用法: $0 [<App路径> <dmg文件名> [卷标名]]" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
DMG_PATH="${OUT_DIR}/${DMG_NAME}"
rm -f "${DMG_PATH}"

APP_BUNDLE="$(basename "${APP_SRC}")"
BACKGROUND="${SCRIPT_DIR}/dmg_background.png"
if [[ ! -f "${BACKGROUND}" ]]; then
  echo "生成 DMG 背景图…" >&2
  python3 "${SCRIPT_DIR}/generate_dmg_background.py" "${BACKGROUND}" || {
    echo "无法生成 ${BACKGROUND}，请确认已安装 PySide6（与 requirements.txt 一致）" >&2
    exit 1
  }
fi

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/gitpullswitchtool-dmg.XXXXXX")"
RW_DMG="$(mktemp -u "${TMPDIR:-/tmp}/gitpullswitchtool-rw.XXXXXX}.dmg")"
cleanup() {
  shopt -s nullglob 2>/dev/null || true
  for _v in /Volumes/"${VOL_NAME}"*; do
    [[ -d "${_v}" ]] && hdiutil detach "${_v}" -quiet 2>/dev/null || true
  done
  rm -f "${RW_DMG}"
  rm -rf "${STAGING}"
}
trap cleanup EXIT

ditto "${APP_SRC}" "${STAGING}/${APP_BUNDLE}"

# 未压缩 .app 常 >1GB，HFS 镜像须大于 du 值（约 +25%）
STAGING_MB="$(du -sm "${STAGING}" | awk '{print $1}')"
SIZE_MB=$(( STAGING_MB + STAGING_MB / 4 + 80 ))
(( SIZE_MB < 512 )) && SIZE_MB=512

shopt -s nullglob 2>/dev/null || true
for _v in /Volumes/"${VOL_NAME}"*; do
  [[ -d "${_v}" ]] && hdiutil detach "${_v}" -force -quiet 2>/dev/null || true
done

hdiutil create -size "${SIZE_MB}m" -fs HFS+ -volname "${VOL_NAME}" -ov "${RW_DMG}" >/dev/null

ATTACH_OUT="$(hdiutil attach -readwrite -noverify -noautoopen "${RW_DMG}")"
VOL_MOUNT="$(echo "${ATTACH_OUT}" | grep '/Volumes/' | tail -1 | awk -F'\t' '{print $3}')"
if [[ -z "${VOL_MOUNT}" ]] || [[ ! -d "${VOL_MOUNT}" ]]; then
  VOL_MOUNT="$(echo "${ATTACH_OUT}" | grep -oE '/Volumes/[^	]+' | tail -1)"
fi
if [[ ! -d "${VOL_MOUNT}" ]]; then
  echo "无法挂载临时 DMG" >&2
  exit 1
fi
DISK_NAME="$(basename "${VOL_MOUNT}")"

ditto "${STAGING}/${APP_BUNDLE}" "${VOL_MOUNT}/${APP_BUNDLE}"
rm -f "${VOL_MOUNT}/Applications" "${VOL_MOUNT}/安装说明.txt"

# 兜底：即使 Finder 背景未写入 .DS_Store，用户也能看到文字说明
cat > "${VOL_MOUNT}/安装说明.txt" <<'EOF'
请将左侧应用图标拖到右侧「应用程序」文件夹完成安装。

Drag the app icon into the Applications folder to install.
EOF

mkdir -p "${VOL_MOUNT}/.background"
cp -f "${BACKGROUND}" "${VOL_MOUNT}/.background/background.png"
BG_TIFF="${VOL_MOUNT}/.background/background.tiff"
if command -v sips >/dev/null 2>&1; then
  sips -s format tiff "${BACKGROUND}" --out "${BG_TIFF}" >/dev/null 2>&1
else
  cp -f "${BACKGROUND}" "${BG_TIFF}"
fi

# Finder 写入 .DS_Store（须在本机图形会话下运行；顺序参考 create-dmg / StackOverflow）
osascript <<APPLESCRIPT || echo "警告: Finder 窗口布局设置失败，DMG 仍可用（请查看「安装说明.txt」）" >&2
tell application "Finder"
  tell disk "${DISK_NAME}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {${WIN_X}, ${WIN_Y}, $((WIN_X + WIN_W)), $((WIN_Y + WIN_H))}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to ${ICON_SIZE}
    set background picture of viewOptions to file ".background:background.tiff"
    try
      make new alias file at container window to POSIX file "/Applications" with properties {name:"Applications"}
    end try
    set position of item "${APP_BUNDLE}" of container window to {${APP_ICON_X}, ${APP_ICON_Y}}
    set position of item "Applications" of container window to {${APPS_ICON_X}, ${APPS_ICON_Y}}
    set position of item "安装说明.txt" of container window to {320, 320}
    update without registering applications
    delay 5
    close
  end tell
end tell
APPLESCRIPT

if command -v bless >/dev/null 2>&1; then
  bless --folder "${VOL_MOUNT}" --openfolder 2>/dev/null || true
fi
if command -v SetFile >/dev/null 2>&1; then
  SetFile -a C "${VOL_MOUNT}" 2>/dev/null || true
fi

sync
sleep 1
sync
hdiutil detach "${VOL_MOUNT}" -quiet
hdiutil convert "${RW_DMG}" -format UDZO -imagekey zlib-level=9 -o "${DMG_PATH}" >/dev/null
rm -f "${RW_DMG}"
RW_DMG=""

echo "已生成: ${DMG_PATH}"
echo "安装：将 ${APP_BUNDLE} 拖到「应用程序」图标上完成安装"
