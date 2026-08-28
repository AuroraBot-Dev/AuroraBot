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

if ! command -v uv &>/dev/null; then
  echo "Error: 未找到 uv。请先安装 uv，参见 https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if ! confirm "确认将 aurora 安装到用户工具目录 $TOOL_BIN 吗？"; then
  echo "已取消安装，脚本退出。"
  exit 1
fi

INDEX_URL=$(sed -n 's/^index-url[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' "$REPO_ROOT/pyproject.toml" | tail -1)
if [ -n "$INDEX_URL" ]; then
  uv tool install --editable --force --index-url "$INDEX_URL" "$REPO_ROOT"
else
  uv tool install --editable --force "$REPO_ROOT"
fi

if command -v aurora &>/dev/null; then
  AURORA=aurora
else
  AURORA="$TOOL_BIN/aurora"
  if [ ! -x "$AURORA" ]; then
    echo "Error: 包已安装，但未找到 aurora 命令。请将 $TOOL_BIN 加入 PATH 后重新运行。" >&2
    exit 1
  fi
  if [[ ":$PATH:" != *":$TOOL_BIN:"* ]]; then
    echo "提示: $TOOL_BIN 不在 PATH 中。请将以下内容加入 shell 配置文件（如 ~/.bash_profile 或 ~/.zshrc）："
    echo "  export PATH=\"$TOOL_BIN:\$PATH\""
    echo "当前将使用完整路径 $AURORA 调用。"
  fi
fi

"$AURORA" --root "$REPO_ROOT" setup

echo "Setup complete: $REPO_ROOT"
