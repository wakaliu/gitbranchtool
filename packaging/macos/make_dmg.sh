#!/usr/bin/env bash
# 从 PyInstaller 生成的 .app 制作只读压缩 DMG（无代码签名）。
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
hdiutil create -volname "${VOL_NAME}" -srcfolder "${APP_SRC}" -ov -format UDZO "${DMG_PATH}"
echo "已生成: ${DMG_PATH}"
