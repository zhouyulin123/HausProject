@echo off
chcp 65001 >nul
title 豪斯 AI 家装 - 停止服务
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0manageHaus.ps1" -Action stop
set "STOP_EXIT=%ERRORLEVEL%"
pause
exit /b %STOP_EXIT%
