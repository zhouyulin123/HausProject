@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 豪斯 AI 家装 - 启动器

if /i "%~1"=="--check" goto check

echo ============================================
echo    豪斯 AI 家装定制助手 - 一键启动
echo ============================================
echo.

REM 检查前端依赖是否已安装
if not exist "frontend\node_modules" (
    echo [首次启动] 正在安装前端依赖，请稍候...
    call npm --prefix frontend install
    echo.
)

echo [1/2] 启动后端服务 ^(端口 8081^)...
start "豪斯-后端" cmd /k "cd /d backend && python -m alembic upgrade head && python -m uvicorn app.main:app --port 8081"

echo [2/2] 启动前端服务 ^(端口 8080^)...
start "豪斯-前端" cmd /k "npm --prefix frontend run dev"

echo.
echo 服务启动中，5 秒后自动打开浏览器...
timeout /t 5 >nul
start http://localhost:8080

echo.
echo ============================================
echo   已启动完成！
echo   - 网页地址: http://localhost:8080
echo   - 关闭服务: 直接关掉弹出的两个命令行窗口
echo ============================================
echo.
echo 本窗口可以关闭（不影响服务运行）。
pause
exit /b 0

:check
echo [自检] 当前目录: %CD%
where python >nul 2>nul || (
    echo [失败] 未找到 Python，请先安装或加入 PATH。
    exit /b 1
)
where npm >nul 2>nul || (
    echo [失败] 未找到 npm，请先安装 Node.js 或加入 PATH。
    exit /b 1
)
pushd backend
python -m alembic current
set "CHECK_EXIT=%ERRORLEVEL%"
popd
if not "%CHECK_EXIT%"=="0" (
    echo [失败] 后端环境或数据库迁移配置不可用。
    exit /b %CHECK_EXIT%
)
echo [通过] Python、npm 和数据库迁移环境可用。
exit /b 0
