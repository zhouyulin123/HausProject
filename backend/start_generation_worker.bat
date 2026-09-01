@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
title Haus Generation Worker
python -m app.workers.generation_worker
if errorlevel 1 (
  echo.
  echo Generation Worker 启动失败，请查看上方错误。
  pause
)
