#!/bin/bash
# ===================================================================
# 前端构建 & Nginx 部署脚本
#
# 用法:
#   bash web-deploy.sh build      # 构建前端
#   bash web-deploy.sh restart    # 重启 Nginx
#   bash web-deploy.sh deploy     # 构建 + 重启（一键部署）
#   bash web-deploy.sh status     # 查看 Nginx 状态
# ===================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$PROJECT_DIR/web"
DIST_DIR="$WEB_DIR/dist"
ACTION="${1:-deploy}"

# ── 函数 ──

ensure_deps() {
  if [ ! -d "$WEB_DIR" ]; then
    echo "[ERROR] 前端目录不存在: $WEB_DIR"
    exit 1
  fi

  if ! command -v pnpm >/dev/null 2>&1; then
    echo "[ERROR] 未检测到 pnpm 命令"
    echo "[HINT]  npm install -g pnpm"
    exit 1
  fi

  local lock_file="$WEB_DIR/pnpm-lock.yaml"
  local marker="$WEB_DIR/node_modules/.deps.md5"
  local cur_md5=""
  [ -f "$lock_file" ] && cur_md5=$(md5sum "$lock_file" | awk '{print $1}')
  local last_md5=""
  [ -f "$marker" ] && last_md5=$(cat "$marker")

  if [ -d "$WEB_DIR/node_modules" ] && [ "$cur_md5" = "$last_md5" ] && [ -n "$cur_md5" ]; then
    echo "[INFO] 前端依赖未变更，跳过安装"
    return
  fi

  echo "[INFO] 前端依赖变更 / 首次安装，开始 pnpm install..."
  cd "$WEB_DIR"
  if [ -f "$lock_file" ]; then
    pnpm install --frozen-lockfile || pnpm install
  else
    pnpm install
  fi
  cd "$PROJECT_DIR"

  if [ -n "$cur_md5" ]; then
    echo "$cur_md5" > "$marker"
  fi
  echo "[OK] 前端依赖安装完成"
}

do_build() {
  ensure_deps

  echo "========================================="
  echo "  前端构建"
  echo "  目录: $WEB_DIR"
  echo "========================================="

  cd "$WEB_DIR"
  pnpm run build
  cd "$PROJECT_DIR"

  if [ -f "$DIST_DIR/index.html" ]; then
    echo "[OK] 构建成功: $DIST_DIR"
  else
    echo "[ERROR] 构建失败，未找到 dist/index.html"
    exit 1
  fi
}

do_restart() {
  echo "[INFO] 重启 Nginx..."
  nginx -t 2>&1 || { echo "[ERROR] Nginx 配置有误"; exit 1; }
  systemctl restart nginx
  echo "[OK] Nginx 已重启"
}

do_deploy() {
  do_build
  do_restart
  echo ""
  echo "========================================="
  echo "  部署完成"
  echo "========================================="
}

do_status() {
  systemctl status nginx --no-pager
}

# ── 执行 ──
case "$ACTION" in
  build)   do_build   ;;
  restart) do_restart ;;
  deploy)  do_deploy  ;;
  status)  do_status  ;;
  *)
    echo "用法: $0 <build|restart|deploy|status>"
    exit 1
    ;;
esac
