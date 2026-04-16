@echo off
chcp 65001 >nul
echo =========================================
echo   开发环境启动
echo =========================================
echo.

set PROJECT_DIR=%~dp0
set BACKEND_PORT=9999

echo [INFO] 启动后端服务 (port %BACKEND_PORT%)...
start "后端服务" cmd /k "cd /d %PROJECT_DIR% && .venv\Scripts\python run.py"

echo [INFO] 启动前端服务...
start "前端服务" cmd /k "cd /d %PROJECT_DIR%\web && pnpm dev"

echo.
echo [INFO] 服务已启动，关闭窗口即可停止
echo [INFO] 后端: http://localhost:9999
echo [INFO] 前端: http://localhost:3100
echo.
pause
