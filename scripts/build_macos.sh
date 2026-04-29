#!/usr/bin/env bash
# 一键构建 macOS：.app（onedir）+ UDZO DMG。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m pip install -U pip wheel
python3 -m pip install -r requirements.txt pyinstaller

SPEC="${ROOT}/packaging/pyinstaller/GitPullSwitchTool_macos.spec"
WORK="${ROOT}/packaging/pyinstaller/work-macos"
DIST_APP="${ROOT}/dist/macos-portable"

pyinstaller --noconfirm --clean --distpath "$DIST_APP" --workpath "$WORK" "$SPEC"
chmod +x "${ROOT}/packaging/macos/make_dmg.sh"
"${ROOT}/packaging/macos/make_dmg.sh"
echo "产物: ${DIST_APP}/GitPullSwitchTool.app 与 dist/macos-installer/"
