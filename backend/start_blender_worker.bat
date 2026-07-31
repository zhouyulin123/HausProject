@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
title Haus Blender Worker
python -m app.workers.blender_worker
if errorlevel 1 (
  echo.
  echo Blender Worker 启动失败，请查看上方错误。
  pause
)
