#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PANEL_DIR="$REPO_ROOT/panel"

git -C "$REPO_ROOT" submodule update --init --remote panel

if ! git -C "$REPO_ROOT" diff --quiet -- panel; then
  echo "Note: panel submodule pointer changed. Commit it in the AuroraBot repository: git add panel && git commit" >&2
fi

cd "$PANEL_DIR"

if ! command -v pnpm &>/dev/null; then
  echo "Error: pnpm is not installed. Install it with: npm install -g pnpm" >&2
  exit 1
fi

pnpm install

echo "Update complete: $PANEL_DIR"
