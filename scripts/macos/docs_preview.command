#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCS_DIR="$REPO_ROOT/docs"

cd "$DOCS_DIR"

if ! command -v pnpm &>/dev/null; then
  echo "Error: pnpm is not installed. Install it with: npm install -g pnpm" >&2
  exit 1
fi

pnpm install --frozen-lockfile
pnpm dev
