#!/usr/bin/env bash
# 从 PyInstaller 生成的 .app 制作只读压缩 DMG（无代码签名）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_SRC="${ROOT}/dist/macos-portable/GitPullSwitchTool.app"
OUT_DIR="${ROOT}/dist/macos-installer"
DMG_NAME="GitPullSwitchTool.dmg"
VOL_NAME="GitPullSwitchTool"

if [[ ! -d "${APP_SRC}" ]]; then
  echo "缺少 ${APP_SRC}，请先执行 scripts/build_macos.sh" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
DMG_PATH="${OUT_DIR}/${DMG_NAME}"
rm -f "${DMG_PATH}"
hdiutil create -volname "${VOL_NAME}" -srcfolder "${APP_SRC}" -ov -format UDZO "${DMG_PATH}"
echo "已生成: ${DMG_PATH}"
