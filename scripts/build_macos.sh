#!/usr/bin/env bash
# 一键构建 macOS：默认走双轨脚本（公开 + 可选内部）。
# 仅公开版：./scripts/build_macos.sh --public-only
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${ROOT}/scripts/build_macos_dual.sh" "$@"
