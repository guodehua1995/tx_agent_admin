#!/bin/bash
# ===================================================================
# LiteRAG Linux 启动脚本
#
# 用法:
#   bash start-linux.sh start     # 启动
#   bash start-linux.sh stop      # 停止
#   bash start-linux.sh restart   # 重启
#   bash start-linux.sh status    # 查看状态
#   bash start-linux.sh log       # 查看日志
# ===================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION="${1:-start}"

# ── 配置 ──
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"
PID_FILE="$PROJECT_DIR/run/app.pid"
LOG_FILE="$PROJECT_DIR/run/app.log"
APP_PORT=9999

mkdir -p "$PROJECT_DIR/run"

# ── 函数 ──

check_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] 配置文件不存在: $ENV_FILE"
    echo "[HINT]  cp .env.example .env && 修改配置"
    exit 1
  fi
}

check_venv() {
  if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[ERROR] 虚拟环境不存在: $VENV_DIR"
    echo "[HINT]  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
  fi
}

ensure_deps() {
  # 1）虚拟环境不存在则创建
  if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[INFO] 虚拟环境不存在，开始创建: $VENV_DIR"
    if command -v uv >/dev/null 2>&1; then
      uv venv "$VENV_DIR" --python 3.11
    else
      python3 -m venv "$VENV_DIR"
    fi
    echo "[OK] 虚拟环境创建完成"
  fi

  # 2）依据 requirements.txt md5 判断是否需要重装依赖
  local req_file="$PROJECT_DIR/requirements.txt"
  if [ ! -f "$req_file" ]; then
    echo "[WARN] 未找到 requirements.txt，跳过依赖检查"
    return
  fi
  local marker="$VENV_DIR/.deps.md5"
  local cur_md5
  cur_md5=$(md5sum "$req_file" | awk '{print $1}')
  local last_md5=""
  [ -f "$marker" ] && last_md5=$(cat "$marker")

  if [ "$cur_md5" = "$last_md5" ]; then
    echo "[INFO] Python 依赖未变更，跳过安装"
    return
  fi

  echo "[INFO] 检测到依赖变更 / 首次启动，开始安装 Python 依赖..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install -r "$req_file" --python "$VENV_DIR/bin/python"
  else
    "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null 2>&1 || true
    "$VENV_DIR/bin/pip" install -r "$req_file"
  fi
  echo "$cur_md5" > "$marker"
  echo "[OK] Python 依赖安装完成"
}

get_pid() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE"
}

is_running() {
  local pid=$(get_pid)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

do_start() {
  check_env_file
  ensure_deps

  if is_running; then
    echo "[WARN] 已在运行 (PID: $(get_pid))，无需重复启动"
    exit 0
  fi

  # 加载环境变量（逐行解析，避免 shell 解释 JSON 值）
  while IFS= read -r line || [ -n "$line" ]; do
    # 跳过空行和注释
    [[ -z "$line" || "$line" == \#* ]] && continue
    export "$line"
  done < "$ENV_FILE"

  source "$VENV_DIR/bin/activate"

  echo "========================================="
  echo "  LiteRAG 启动"
  echo "  端口: $APP_PORT"
  echo "  目录: $PROJECT_DIR"
  echo "========================================="

  nohup python -m uvicorn app:app \
    --host 0.0.0.0 \
    --port "$APP_PORT" \
    --workers 2 \
    >> "$LOG_FILE" 2>&1 &

  echo $! > "$PID_FILE"
  sleep 1

  if is_running; then
    echo "[OK] 启动成功 (PID: $(get_pid))"
    echo "[OK] 日志: $LOG_FILE"
  else
    echo "[ERROR] 启动失败，请查看日志: $LOG_FILE"
    exit 1
  fi
}

do_stop() {
  if ! is_running; then
    echo "[INFO] 未在运行"
    rm -f "$PID_FILE"
    return
  fi

  local pid=$(get_pid)
  echo "[INFO] 正在停止 (PID: $pid)..."
  kill "$pid"

  for i in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done

  if kill -0 "$pid" 2>/dev/null; then
    echo "[WARN] 强制终止..."
    kill -9 "$pid" 2>/dev/null
  fi

  rm -f "$PID_FILE"
  echo "[OK] 已停止"
}

do_restart() {
  do_stop
  sleep 1
  do_start
}

do_status() {
  if is_running; then
    echo "[运行中] PID: $(get_pid), PORT: $APP_PORT"
  else
    echo "[未运行]"
  fi
}

do_log() {
  if [ -f "$LOG_FILE" ]; then
    tail -f "$LOG_FILE"
  else
    echo "[INFO] 日志文件不存在"
  fi
}

# ── 执行 ──
case "$ACTION" in
  start)   do_start   ;;
  stop)    do_stop    ;;
  restart) do_restart ;;
  status)  do_status  ;;
  log)     do_log     ;;
  *)
    echo "用法: $0 <start|stop|restart|status|log>"
    exit 1
    ;;
esac
