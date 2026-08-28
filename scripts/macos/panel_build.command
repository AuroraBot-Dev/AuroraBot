#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PANEL_DIR="$REPO_ROOT/panel"

cd "$PANEL_DIR"

if ! command -v pnpm &>/dev/null; then
  echo "Error: 未找到 pnpm。请先安装: npm install -g pnpm" >&2
  exit 1
fi

pnpm install --frozen-lockfile
pnpm build

echo "Build complete: $PANEL_DIR/apps/web/dist"
