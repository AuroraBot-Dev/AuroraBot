#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCS_DIR="$REPO_ROOT/docs"

git -C "$REPO_ROOT" submodule update --init --remote docs

if ! git -C "$REPO_ROOT" diff --quiet -- docs; then
  echo "Note: docs submodule pointer changed. Commit it in the AuroraBot repository: git add docs && git commit" >&2
fi

cd "$DOCS_DIR"

if ! command -v pnpm &>/dev/null; then
  echo "Error: pnpm is not installed. Install it with: npm install -g pnpm" >&2
  exit 1
fi

pnpm install

echo "Update complete: $DOCS_DIR"
