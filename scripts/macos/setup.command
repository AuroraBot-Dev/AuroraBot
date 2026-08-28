#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TOOL_BIN="$HOME/.local/bin"

confirm() {
  local msg="$1"
  read -rp "$msg [Y/N]（回车默认 Y）: " answer
  [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
}

if ! command -v git &>/dev/null; then
  echo "Error: 未找到 git。请先安装 git。" >&2
  exit 1
fi
if ! command -v uv &>/dev/null; then
  echo "Error: 未找到 uv。请先安装 uv，参见 https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
if ! command -v pnpm &>/dev/null; then
  echo "Error: 未找到 pnpm。请先安装: npm install -g pnpm" >&2
  exit 1
fi

LINKED=0
if confirm "确认将 aurora 全局链接到用户工具目录 $TOOL_BIN（editable，不复制项目）吗？"; then
  LINKED=1
  INDEX_URL=$(sed -n 's/^index-url[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' "$REPO_ROOT/pyproject.toml" | tail -1)
  if [ -n "$INDEX_URL" ]; then
    uv tool install --editable --force --index-url "$INDEX_URL" "$REPO_ROOT"
  else
    uv tool install --editable --force "$REPO_ROOT"
  fi
fi

if command -v aurora &>/dev/null; then
  aurora --root "$REPO_ROOT" setup
elif [ "$LINKED" -eq 1 ]; then
  AURORA="$TOOL_BIN/aurora"
  if [ ! -x "$AURORA" ]; then
    echo "Error: 包已链接，但未找到 aurora 命令。请将 $TOOL_BIN 加入 PATH 后重新运行。" >&2
    exit 1
  fi
  if [[ ":$PATH:" != *":$TOOL_BIN:"* ]]; then
    echo "提示: $TOOL_BIN 不在 PATH 中。请将以下内容加入 shell 配置文件（如 ~/.bash_profile 或 ~/.zshrc）："
    echo "  export PATH=\"$TOOL_BIN:\$PATH\""
    echo "当前将使用完整路径 $AURORA 调用。"
  fi
  "$AURORA" --root "$REPO_ROOT" setup
else
  uv run --project "$REPO_ROOT" aurora --root "$REPO_ROOT" setup
fi

echo "Setup complete: $REPO_ROOT"
