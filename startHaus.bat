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
if /i "%~1"=="--stop" goto stop
if /i "%~1"=="--status" goto status

if not defined PYTHON_CMD (
    echo [失败] 未找到包含 FastAPI/Alembic 依赖的 Python。可设置 HAUS_PYTHON 或创建 backend\.venv。
    exit /b 1
)

echo ============================================
echo    豪斯 AI 家装定制助手 - 一键启动
echo ============================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0manageHaus.ps1" -Action start
set "LAUNCH_EXIT=%ERRORLEVEL%"
pause
exit /b %LAUNCH_EXIT%

:stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0manageHaus.ps1" -Action stop
exit /b %ERRORLEVEL%

:status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0manageHaus.ps1" -Action status
exit /b %ERRORLEVEL%

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
