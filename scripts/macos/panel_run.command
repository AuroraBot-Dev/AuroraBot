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

if ! curl -fsS http://127.0.0.1:8765/healthz >/dev/null 2>&1; then
  echo "Warning: AuroraBot 后端不可达: http://127.0.0.1:8765" >&2
  echo "请先在仓库根目录运行 uv run aurora start 启动后端。" >&2
fi

pnpm install --frozen-lockfile
pnpm dev
