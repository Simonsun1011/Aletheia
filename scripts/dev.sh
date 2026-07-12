#!/usr/bin/env bash
# 一条命令起 Aletheia 本地开发：后端 :8000 + 前端 :3000（均绑 127.0.0.1）
# 用法（仓库根目录）：./scripts/dev.sh
# 端口被残留占用时：./scripts/dev.sh --kill-ports  先释放再启
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BACKEND_HOST="${ALETHEIA_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${ALETHEIA_BACKEND_PORT:-8000}"
FRONTEND_HOST="${ALETHEIA_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${ALETHEIA_FRONTEND_PORT:-3000}"
KILL_PORTS=0
for arg in "$@"; do
  case "$arg" in
    --kill-ports|-k) KILL_PORTS=1 ;;
    -h|--help)
      echo "用法: ./scripts/dev.sh [--kill-ports|-k]"
      echo "  同时启动后端 :${BACKEND_PORT} 与前端 :${FRONTEND_PORT}"
      echo "  --kill-ports  先释放被占用的本机端口再启动"
      exit 0
      ;;
  esac
done

if [[ ! -x "$ROOT/.venv/bin/uvicorn" ]]; then
  echo "缺少 .venv/bin/uvicorn。请先在仓库根创建虚拟环境并安装依赖。" >&2
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "缺少 frontend/node_modules。请先：cd frontend && npm install" >&2
  exit 1
fi

port_pids() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null || true
}

port_busy() {
  [[ -n "$(port_pids "$1")" ]]
}

free_port() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "释放端口 ${port}（PID: $(echo "$pids" | tr '\n' ' ')）…"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 0.6
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
    sleep 0.3
  fi
  if port_busy "$port"; then
    echo "无法释放端口 ${port}，请手动：lsof -nP -iTCP:${port} -sTCP:LISTEN" >&2
    exit 1
  fi
}

ensure_port() {
  local port="$1"
  if ! port_busy "$port"; then
    return 0
  fi
  if [[ "$KILL_PORTS" -eq 1 ]]; then
    free_port "$port"
    return 0
  fi
  echo "端口 ${port} 已被占用。可二选一：" >&2
  echo "  ./scripts/dev.sh --kill-ports     # 自动释放本机 8000/3000 再启动" >&2
  echo "  lsof -nP -iTCP:${port} -sTCP:LISTEN && kill <PID>" >&2
  exit 1
}

ensure_port "$BACKEND_PORT"
ensure_port "$FRONTEND_PORT"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "正在停止…"
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    local pids
    pids="$(port_pids "$port")"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
    fi
  done
  echo "已停止。前端 http://${FRONTEND_HOST}:${FRONTEND_PORT}"
}

trap cleanup EXIT INT TERM

echo "启动后端  http://${BACKEND_HOST}:${BACKEND_PORT}"
"$ROOT/.venv/bin/uvicorn" backend.app.main:app \
  --host "$BACKEND_HOST" \
  --port "$BACKEND_PORT" \
  --reload &
BACKEND_PID=$!

echo "启动前端  http://${FRONTEND_HOST}:${FRONTEND_PORT}"
(
  cd "$ROOT/frontend"
  npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

echo ""
echo "浏览器打开：http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "Ctrl+C 同时停下前后端。"
echo ""

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done
exit 0
