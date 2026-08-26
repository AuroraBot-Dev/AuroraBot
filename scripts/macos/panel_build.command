#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PANEL_DIR="$REPO_ROOT/panel"

cd "$PANEL_DIR"

if ! command -v pnpm &>/dev/null; then
  echo "Error: pnpm is not installed. Install it with: npm install -g pnpm" >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  echo "Error: dependencies are missing. Run scripts/macos/panel_setup.command first." >&2
  exit 1
fi

pnpm build

echo "Build complete: $PANEL_DIR/apps/web/dist"
