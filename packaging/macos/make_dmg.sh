#!/usr/bin/env bash
# 从 PyInstaller 生成的 .app 制作只读压缩 DMG（无代码签名）。
# 提示使用与 .app 相同坐标的占位文件 + 自定义图标（位置可靠、无 PNG 预览框）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${ROOT}/dist/macos-installer"
CREATE_DMG="${SCRIPT_DIR}/create-dmg/create-dmg"

APP_SRC="${1:-${ROOT}/dist/macos-portable/GitPullSwitchTool.app}"
DMG_NAME="${2:-GitPullSwitchTool.dmg}"
VOL_NAME="${3:-$(basename "${APP_SRC}" .app)}"

WIN_X=400
WIN_Y=100
WIN_W=660
WIN_H=430
ICON_SIZE=128
APP_ICON_X=160
APP_ICON_Y=180
APPS_ICON_X=480
APPS_ICON_Y=180
HINT_ICON_X=320
HINT_ICON_Y=180
HINT_FILE_NAME=$'\xc2\xa0.png'

set_custom_icon() {
  local target="$1"
  local icon_png="$2"
  /usr/bin/osascript - "$target" "$icon_png" <<'APPLESCRIPT'
use framework "AppKit"
use scripting additions

on run argv
  set targetPath to item 1 of argv
  set iconPath to item 2 of argv
  set iconImage to current application's NSImage's alloc()'s initWithContentsOfFile:iconPath
  current application's NSWorkspace's sharedWorkspace()'s setIcon:iconImage forFile:targetPath options:0
end run
APPLESCRIPT
}

if [[ ! -d "${APP_SRC}" ]]; then
  echo "缺少 .app：${APP_SRC}" >&2
  exit 1
fi
if [[ ! -x "${CREATE_DMG}" ]]; then
  echo "缺少 create-dmg：${CREATE_DMG}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
DMG_PATH="${OUT_DIR}/${DMG_NAME}"
rm -f "${DMG_PATH}"

APP_BUNDLE="$(basename "${APP_SRC}")"
BACKGROUND="${SCRIPT_DIR}/dmg_background.png"
HINT="${SCRIPT_DIR}/dmg_hint.png"
HINT_PREP="${SCRIPT_DIR}/.dmg-hint-prepared.png"

echo "生成 DMG 资源…" >&2
python3 "${SCRIPT_DIR}/generate_dmg_background.py" "${BACKGROUND}" "${HINT}" || {
  echo "无法生成资源，请确认已安装 PySide6" >&2
  exit 1
}

cp -f "${HINT}" "${HINT_PREP}"
set_custom_icon "${HINT_PREP}" "${HINT}"

STAGING="$(mktemp -d "${TMPDIR:-/tmp}/gitpullswitchtool-dmg.XXXXXX")"
cleanup() {
  shopt -s nullglob 2>/dev/null || true
  for _v in /Volumes/"${VOL_NAME}"*; do
    [[ -d "${_v}" ]] && hdiutil detach "${_v}" -quiet 2>/dev/null || true
  done
  rm -rf "${STAGING}"
}
trap cleanup EXIT

ditto "${APP_SRC}" "${STAGING}/${APP_BUNDLE}"

STAGING_MB="$(du -sm "${STAGING}" | awk '{print $1}')"
DISK_IMAGE_SIZE=$(( STAGING_MB + STAGING_MB / 4 + 80 ))
(( DISK_IMAGE_SIZE < 512 )) && DISK_IMAGE_SIZE=512

shopt -s nullglob 2>/dev/null || true
for _v in /Volumes/"${VOL_NAME}"*; do
  [[ -d "${_v}" ]] && hdiutil detach "${_v}" -force -quiet 2>/dev/null || true
done

"${CREATE_DMG}" \
  --volname "${VOL_NAME}" \
  --background "${BACKGROUND}" \
  --window-pos "${WIN_X}" "${WIN_Y}" \
  --window-size "${WIN_W}" "${WIN_H}" \
  --icon-size "${ICON_SIZE}" \
  --icon "${APP_BUNDLE}" "${APP_ICON_X}" "${APP_ICON_Y}" \
  --app-drop-link "${APPS_ICON_X}" "${APPS_ICON_Y}" \
  --add-file "${HINT_FILE_NAME}" "${HINT_PREP}" "${HINT_ICON_X}" "${HINT_ICON_Y}" \
  --hide-extension "${APP_BUNDLE}" \
  --hide-extension "${HINT_FILE_NAME}" \
  --disk-image-size "${DISK_IMAGE_SIZE}" \
  --bless \
  --no-internet-enable \
  "${DMG_PATH}" \
  "${STAGING}"

echo "已生成: ${DMG_PATH}"
echo "安装：将 ${APP_BUNDLE} 拖到「应用程序」图标上完成安装"
