#!/usr/bin/env bash
# 一键构建 macOS：.app（onedir）+ UDZO DMG。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m pip install -U pip wheel
python3 -m pip install -r requirements.txt pyinstaller --no-compile

# 为了让 PyInstaller 生成 universal2，需要把依赖中的 native 扩展（.so/.dylib）
# 做成 fat 二进制（arm64 + x86_64）。这里仅处理已知会触发 fatness 校验的包。
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
WORK="${ROOT}/packaging/pyinstaller/work-macos"
DIST_APP="${ROOT}/dist/macos-portable"

pyinstaller --noconfirm --clean --distpath "$DIST_APP" --workpath "$WORK" "$SPEC"
chmod +x "${ROOT}/packaging/macos/make_dmg.sh"
"${ROOT}/packaging/macos/make_dmg.sh"
echo "产物: ${DIST_APP}/GitPullSwitchTool.app 与 dist/macos-installer/"
