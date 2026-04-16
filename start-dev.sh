#!/bin/bash
# LiteRAG 开发环境启动脚本 (macOS / Linux)
# 用法: bash start-dev.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_PORT=9999

cleanup() {
  echo ""
  echo "[INFO] 正在停止服务..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
  echo "[INFO] 服务已停止"
  exit 0
}

trap cleanup SIGINT SIGTERM

echo "========================================="
echo "  LiteRAG 开发环境启动"
echo "========================================="

# 启动后端
echo "[INFO] 启动后端服务 (port $BACKEND_PORT)..."
cd "$PROJECT_DIR"
uvicorn app:app --reload --port $BACKEND_PORT &
BACKEND_PID=$!

# 启动前端
echo "[INFO] 启动前端服务..."
cd "$PROJECT_DIR/web"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "[INFO] 后端 PID: $BACKEND_PID"
echo "[INFO] 前端 PID: $FRONTEND_PID"
echo "[INFO] 按 Ctrl+C 停止所有服务"
echo ""

wait
