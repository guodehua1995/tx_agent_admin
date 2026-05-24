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

do_build() {
  if [ ! -d "$WEB_DIR/node_modules" ]; then
    echo "[ERROR] 前端依赖未安装"
    echo "[HINT]  cd web && pnpm install"
    exit 1
  fi

  echo "========================================="
  echo "  前端构建"
  echo "  目录: $WEB_DIR"
  echo "========================================="

  cd "$WEB_DIR"
  pnpm run build

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
