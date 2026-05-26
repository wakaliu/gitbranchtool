#!/usr/bin/env bash
# 从 PyInstaller 生成的 .app 制作只读压缩 DMG（无代码签名）。
# 使用 Finder 别名指向 /Applications：符号链接在 DMG 内常显示为 App Store 图标且拖放无效。
# 用法：
#   ./make_dmg.sh                                    # 默认：GitPullSwitchTool.app -> GitPullSwitchTool.dmg
#   ./make_dmg.sh <App路径> <dmg文件名> [卷标名]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${ROOT}/dist/macos-installer"

APP_SRC="${1:-${ROOT}/dist/macos-portable/GitPullSwitchTool.app}"
DMG_NAME="${2:-GitPullSwitchTool.dmg}"
VOL_NAME="${3:-$(basename "${APP_SRC}" .app)}"

if [[ ! -d "${APP_SRC}" ]]; then
  echo "缺少 .app：${APP_SRC}" >&2
  echo "用法: $0 [<App路径> <dmg文件名> [卷标名]]" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
DMG_PATH="${OUT_DIR}/${DMG_NAME}"
rm -f "${DMG_PATH}"

APP_BUNDLE="$(basename "${APP_SRC}")"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/gitpullswitchtool-dmg.XXXXXX")"
cleanup() { rm -rf "${STAGING}"; }
trap cleanup EXIT

ditto "${APP_SRC}" "${STAGING}/${APP_BUNDLE}"
rm -f "${STAGING}/Applications"

if ! osascript -e "tell application \"Finder\" to make new alias file at (POSIX file \"${STAGING}\" as alias) to (POSIX file \"/Applications\" as alias) with properties {name:\"Applications\"}"; then
  echo "警告: Finder 别名创建失败，回退符号链接（拖放可能无效）" >&2
  ln -sf /Applications "${STAGING}/Applications"
fi

hdiutil create -volname "${VOL_NAME}" -srcfolder "${STAGING}" -ov -format UDZO "${DMG_PATH}"
echo "已生成: ${DMG_PATH}"
echo "安装：将 ${APP_BUNDLE} 拖到「应用程序」图标上完成安装"
