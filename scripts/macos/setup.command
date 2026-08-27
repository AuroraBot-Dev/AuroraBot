#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if ! command -v uv &>/dev/null; then
  echo "Error: 未找到 uv。请先安装 uv，参见 https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv tool install --editable --force "$REPO_ROOT"

if command -v aurora &>/dev/null; then
  AURORA=aurora
else
  AURORA="$HOME/.local/bin/aurora"
  if [ ! -x "$AURORA" ]; then
    echo "Error: 包已安装，但未找到 aurora 命令。请将 $HOME/.local/bin 加入 PATH 后重新运行。" >&2
    exit 1
  fi
fi

"$AURORA" --root "$REPO_ROOT" setup

echo "Setup complete: $REPO_ROOT"
