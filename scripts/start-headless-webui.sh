#!/usr/bin/env bash
# 快速启动：AuroraBot 无头后端 + Panel Web UI（本地开发用，不提交）。
#
# 用法：
#   ./scripts/start-headless-webui.sh
#   ./scripts/start-headless-webui.sh --platform mcp
#
# 后端默认监听 http://127.0.0.1:8765，Panel 开发服务器默认监听 http://127.0.0.1:8766。
# 登录令牌位于 data/ops/Token.txt。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PANEL_DIR="$ROOT/panel"
LOG_DIR="$ROOT/logs"
BACKEND_LOG="$LOG_DIR/headless-backend.log"
PANEL_LOG="$LOG_DIR/headless-panel.log"
BACKEND_PORT="${AURORA_BACKEND_PORT:-8765}"
PANEL_PORT="${AURORA_PANEL_PORT:-8766}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
PANEL_URL="http://127.0.0.1:${PANEL_PORT}"

mkdir -p "$LOG_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "错误: 未找到 uv，请先安装 uv 并确保在 PATH 中。" >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "错误: 未找到 pnpm，请先安装 pnpm（Node 22.18+ / pnpm 11+）。" >&2
  exit 1
fi

if [ ! -d "$PANEL_DIR/apps/web" ]; then
  echo "错误: 未找到 panel 子模块，请先初始化 submodule: git submodule update --init --recursive" >&2
  exit 1
fi

BACKEND_PID=""
PANEL_PID=""

cleanup() {
  echo
  echo "正在停止后端与 Panel..."
  if [ -n "$PANEL_PID" ] && kill -0 "$PANEL_PID" 2>/dev/null; then
    kill "$PANEL_PID" 2>/dev/null || true
    wait "$PANEL_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  echo "已停止。"
}
trap cleanup EXIT INT TERM

wait_for_url() {
  local url="$1"
  local name="$2"
  local tries="${3:-60}"
  local delay="${4:-0.5}"
  echo "等待 $name 就绪: $url"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name 已就绪。"
      return 0
    fi
    sleep "$delay"
  done
  echo "错误: $name 在 ${tries} 次尝试后仍未就绪，日志: $LOG_DIR" >&2
  return 1
}

echo "启动 AuroraBot 无头后端..."
(
  cd "$ROOT"
  exec uv run aurora start --headless "$@"
) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

wait_for_url "$BACKEND_URL/healthz" "后端" 60 0.5

echo "启动 Panel 开发服务器..."
(
  cd "$PANEL_DIR"
  exec pnpm dev
) >"$PANEL_LOG" 2>&1 &
PANEL_PID=$!

wait_for_url "$PANEL_URL" "Panel" 60 1

TOKEN_FILE="$ROOT/data/ops/Token.txt"
echo
echo "=============================================="
echo " AuroraBot 无头模式 + Panel Web UI 已启动"
echo " Panel:  $PANEL_URL"
echo " 后端:   $BACKEND_URL"
if [ -f "$TOKEN_FILE" ]; then
  echo " 登录令牌: $(cat "$TOKEN_FILE")"
else
  echo " 登录令牌: $TOKEN_FILE （尚未生成，请稍候查看）"
fi
echo " 后端日志: $BACKEND_LOG"
echo " Panel日志: $PANEL_LOG"
echo " 按 Ctrl+C 停止。"
echo "=============================================="

wait "$BACKEND_PID"
