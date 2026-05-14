#!/usr/bin/env bash
# macOS 双轨打包（与 Windows build_windows_dual 对齐）：
# - 公开版：不内置仓库根 sausage_projects.yaml，产物 GitPullSwitchTool.app + GitPullSwitchTool.dmg
# - 内部版：GITTOOL_SAUSAGE_INTERNAL=1，打入仓库根 sausage_projects.yaml；若根目录无该文件则临时复制
#   src/git_gui/bundle_data/sausage_projects.yaml 打完即删（与 build_windows_dual.ps1 一致）
# 均为 universal2（Apple Silicon + Intel）。
# 可选：--public-only  仅打公开版
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PUBLIC_ONLY=0
for arg in "$@"; do
  if [[ "${arg}" == "--public-only" ]]; then
    PUBLIC_ONLY=1
  fi
done

python3 -m pip install -U pip wheel
python3 -m pip install -r requirements.txt pyinstaller --no-compile

if ! python3 -c "from PySide6.QtWidgets import QApplication" 2>/dev/null; then
  echo "PySide6 图形模块不可用（常见于 site-packages 中缺失 QtWidgets.abi3.so）。请重装与 requirements 一致的版本，例如：" >&2
  echo "  python3 -m pip install --force-reinstall -r ${ROOT}/requirements.txt" >&2
  exit 1
fi

if ! arch -arm64 uname -m >/dev/null 2>&1; then
  echo "universal2 构建需要在 Apple Silicon 环境上执行。" >&2
  exit 1
fi
if ! arch -x86_64 uname -m >/dev/null 2>&1; then
  echo "x86_64 依赖需要 Rosetta（无法用 arch -x86_64 运行）。" >&2
  exit 1
fi

LIPO_BIN="$(command -v lipo || true)"
if [[ -z "${LIPO_BIN}" ]]; then
  echo "未找到 lipo 命令，请安装 Xcode 命令行工具。" >&2
  exit 1
fi

psutil_version="$(python3 -c "import psutil; print(psutil.__version__)" )"
psutil_so_dest="$(python3 -c "import psutil, pathlib; print(pathlib.Path(psutil.__file__).parent/'_psutil_osx.abi3.so')" )"
pyyaml_version="$(python3 -c "import yaml; print(yaml.__version__)" )"
pyyaml_so_dest="$(python3 -c "import yaml as y, pathlib; p=pathlib.Path(y.__file__).parent; print(next(p.glob('_yaml*.so')))" )"

so_is_universal2() {
  local so_path="$1"
  file "${so_path}" | python3 -c "import sys; txt=sys.stdin.read().lower(); raise SystemExit(0 if 'universal binary' in txt else 1)"
}

ensure_fat_so() {
  local pkg="$1"
  local version="$2"
  local dest_so="$3"
  local arm_install_path="$TMP_DIR/arm"
  local x86_install_path="$TMP_DIR/x86"

  if so_is_universal2 "${dest_so}"; then
    return 0
  fi

  rm -rf "${TMP_DIR}"
  mkdir -p "${TMP_DIR}/arm" "${TMP_DIR}/x86"

  arch -arm64 python3 -m pip install --no-compile --target "${arm_install_path}" "${pkg}==${version}"
  arch -x86_64 python3 -m pip install --no-compile --target "${x86_install_path}" "${pkg}==${version}"

  if [[ "${pkg}" == "psutil" ]]; then
    arm_so="${arm_install_path}/psutil/_psutil_osx.abi3.so"
    x86_so="${x86_install_path}/psutil/_psutil_osx.abi3.so"
  else
    arm_so="$(python3 -c "import pathlib, os; p=pathlib.Path(os.environ['ARM_YAML_DIR']); print(next(p.glob('_yaml*.so')))" )"
    x86_so="$(python3 -c "import pathlib, os; p=pathlib.Path(os.environ['X86_YAML_DIR']); print(next(p.glob('_yaml*.so')))" )"
  fi

  "${LIPO_BIN}" -create "${arm_so}" "${x86_so}" -output "${dest_so}"
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

ensure_fat_so "psutil" "${psutil_version}" "${psutil_so_dest}"
export ARM_YAML_DIR="${TMP_DIR}/arm/yaml"
export X86_YAML_DIR="${TMP_DIR}/x86/yaml"
ensure_fat_so "PyYAML" "${pyyaml_version}" "${pyyaml_so_dest}"

SPEC="${ROOT}/packaging/pyinstaller/GitPullSwitchTool_macos.spec"
DIST_APP="${ROOT}/dist/macos-portable"
MAKE_DMG="${ROOT}/packaging/macos/make_dmg.sh"
mkdir -p "${DIST_APP}"

unset GITTOOL_SAUSAGE_INTERNAL || true
python3 -m PyInstaller --noconfirm --clean --distpath "$DIST_APP" --workpath "${ROOT}/packaging/pyinstaller/work-macos-public" "$SPEC"
chmod +x "${MAKE_DMG}"
"${MAKE_DMG}" "${DIST_APP}/GitPullSwitchTool.app" "GitPullSwitchTool.dmg" "GitPullSwitchTool"
echo "公开版: ${DIST_APP}/GitPullSwitchTool.app 与 dist/macos-installer/GitPullSwitchTool.dmg"

if [[ "${PUBLIC_ONLY}" -eq 1 ]]; then
  exit 0
fi

ROOT_YAML="${ROOT}/sausage_projects.yaml"
TEMPLATE_YAML="${ROOT}/src/git_gui/bundle_data/sausage_projects.yaml"
TEMP_INTERNAL_YAML=0
if [[ ! -f "${ROOT_YAML}" ]]; then
  if [[ ! -f "${TEMPLATE_YAML}" ]]; then
    echo "未找到 ${ROOT_YAML} 与模板 ${TEMPLATE_YAML}，跳过内部版。" >&2
    exit 0
  fi
  cp -f "${TEMPLATE_YAML}" "${ROOT_YAML}"
  TEMP_INTERNAL_YAML=1
  echo "警告: 使用 bundle 模板作为临时 sausage_projects.yaml 打内部版，构建结束后将删除该文件。" >&2
fi

export GITTOOL_SAUSAGE_INTERNAL=1
python3 -m PyInstaller --noconfirm --clean --distpath "$DIST_APP" --workpath "${ROOT}/packaging/pyinstaller/work-macos-sausage" "$SPEC"
unset GITTOOL_SAUSAGE_INTERNAL || true
"${MAKE_DMG}" "${DIST_APP}/GitPullSwitchTool-Sausage.app" "GitPullSwitchTool-Sausage.dmg" "GitPullSwitchTool-Sausage"
if [[ "${TEMP_INTERNAL_YAML}" -eq 1 ]]; then
  rm -f "${ROOT_YAML}"
  echo "已删除临时 sausage_projects.yaml"
fi
echo "内部版: ${DIST_APP}/GitPullSwitchTool-Sausage.app 与 dist/macos-installer/GitPullSwitchTool-Sausage.dmg"
