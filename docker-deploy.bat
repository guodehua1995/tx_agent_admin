@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   TX Agent Admin - Docker 一键部署
echo ============================================
echo.

:: 检查 Docker 是否运行
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] Docker 未运行，请先启动 Docker Desktop
    pause
    exit /b 1
)

:: 检查 .env.docker 是否存在
if not exist ".env.docker" (
    echo [错误] 未找到 .env.docker 配置文件
    echo 请复制 .env.docker.example 为 .env.docker 并配置数据库密码等参数
    pause
    exit /b 1
)

echo [1/3] 选择部署模式:
echo   A - 仅应用（连接宿主机/远程数据库）
echo   B - 应用 + 容器内数据库（全新环境）
echo.
set /p MODE="请选择 (A/B): "

if /i "%MODE%"=="B" (
    echo.
    echo [2/3] 构建并启动应用 + 数据库...
    docker-compose --profile with-db up -d --build
) else (
    echo.
    echo [2/3] 构建并启动应用（使用外部数据库）...
    docker-compose up -d --build
)

if %errorlevel% neq 0 (
    echo.
    echo [错误] 部署失败，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 部署完成！
echo ============================================
echo   访问地址: http://localhost:9999
echo   查看日志: docker-compose logs -f app
echo   停止服务: docker-compose down
echo ============================================
echo.
pause
