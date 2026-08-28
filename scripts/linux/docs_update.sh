#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCS_DIR="$REPO_ROOT/docs"

if [ -e "$DOCS_DIR/.git" ] && ! git -C "$DOCS_DIR" diff --quiet 2>/dev/null; then
  echo "Error: docs 子模块有未提交的更改。请先提交或暂存后再更新。" >&2
  exit 1
fi

git -C "$REPO_ROOT" submodule update --init --remote docs

if ! git -C "$REPO_ROOT" diff --quiet -- docs; then
  echo "Note: docs 子模块指针已变更。请在 AuroraBot 仓库中提交: git add docs && git commit" >&2
fi

cd "$DOCS_DIR"

if ! command -v pnpm &>/dev/null; then
  echo "Error: 未找到 pnpm。请先安装: npm install -g pnpm" >&2
  exit 1
fi

pnpm install

echo "Update complete: $DOCS_DIR"
