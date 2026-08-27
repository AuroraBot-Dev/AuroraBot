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
  echo "Error: dependencies are missing. Run scripts/linux/panel_setup.sh first." >&2
  exit 1
fi

if ! curl -fsS http://127.0.0.1:8765/healthz >/dev/null 2>&1; then
  echo "Warning: AuroraBot backend is not reachable at http://127.0.0.1:8765." >&2
  echo "Start it with \"uv run aurora start\" in the repository root first." >&2
fi

pnpm dev
