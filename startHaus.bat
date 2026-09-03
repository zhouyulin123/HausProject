@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 豪斯 AI 家装 - 启动器

REM Python 解析顺序：显式 HAUS_PYTHON > 项目虚拟环境 > py 3.12 > py 3.14 > PATH python
set "PYTHON_CMD="
if defined HAUS_PYTHON if exist "%HAUS_PYTHON%" set PYTHON_CMD="%HAUS_PYTHON%"
if not defined PYTHON_CMD if exist "backend\.venv\Scripts\python.exe" set PYTHON_CMD="%CD%\backend\.venv\Scripts\python.exe"
if not defined PYTHON_CMD (
    where py >nul 2>nul && py -3.12 -c "import fastapi, alembic" >nul 2>nul && set "PYTHON_CMD=py -3.12"
)
if not defined PYTHON_CMD (
    where py >nul 2>nul && py -3.14 -c "import fastapi, alembic" >nul 2>nul && set "PYTHON_CMD=py -3.14"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul && python -c "import fastapi, alembic" >nul 2>nul && set "PYTHON_CMD=python"
)

if /i "%~1"=="--check" goto check

if not defined PYTHON_CMD (
    echo [失败] 未找到包含 FastAPI/Alembic 依赖的 Python。可设置 HAUS_PYTHON 或创建 backend\.venv。
    exit /b 1
)

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
start "豪斯-后端" cmd /k "cd /d backend && %PYTHON_CMD% -m alembic upgrade head && %PYTHON_CMD% -m uvicorn app.main:app --port 8081"

echo [2/2] 启动前端服务 ^(端口 8080^)...
start "豪斯-前端" cmd /k "npm --prefix frontend run dev"

echo.
echo 正在等待前后端服务就绪...
call :wait_for_url "http://127.0.0.1:8081/ready" 45 "后端服务"
if errorlevel 1 exit /b 1
call :wait_for_url "http://127.0.0.1:8080/" 45 "前端服务"
if errorlevel 1 exit /b 1
start http://127.0.0.1:8080

echo.
echo ============================================
echo   已启动完成！
echo   - 网页地址: http://127.0.0.1:8080
echo   - 关闭服务: 直接关掉弹出的两个命令行窗口
echo ============================================
echo.
echo 本窗口可以关闭（不影响服务运行）。
pause
exit /b 0

:wait_for_url
for /l %%I in (1,1,%~2) do (
    powershell.exe -NoProfile -Command "$ProgressPreference = 'SilentlyContinue'; try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%~1' -TimeoutSec 2; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { exit 0 } } catch {}; exit 1" >nul 2>nul && (
        echo [就绪] %~3
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)
echo [失败] %~3 在 %~2 秒内未就绪，请查看对应服务窗口中的错误信息。
exit /b 1

:check
echo [自检] 当前目录: %CD%
if not defined PYTHON_CMD (
    echo [失败] 未找到包含 FastAPI/Alembic 依赖的 Python。可设置 HAUS_PYTHON 或创建 backend\.venv。
    exit /b 1
)
where npm >nul 2>nul || (
    echo [失败] 未找到 npm，请先安装 Node.js 或加入 PATH。
    exit /b 1
)
pushd backend
%PYTHON_CMD% -m alembic current
set "CHECK_EXIT=%ERRORLEVEL%"
if "%CHECK_EXIT%"=="0" %PYTHON_CMD% -m app.db.schema_readiness
set "CHECK_EXIT=%ERRORLEVEL%"
if "%CHECK_EXIT%"=="0" %PYTHON_CMD% -c "from app.main import app; from app.core.config import settings; print('app_import=ok'); print('llm_key_configured=' + str(bool(settings.llm_api_key))); raise SystemExit(0 if settings.llm_api_key else 2)"
set "CHECK_EXIT=%ERRORLEVEL%"
popd
if not "%CHECK_EXIT%"=="0" (
    echo [失败] 后端环境或数据库迁移配置不可用。
    exit /b %CHECK_EXIT%
)
echo [通过] Python、npm 和数据库迁移环境可用。
exit /b 0
