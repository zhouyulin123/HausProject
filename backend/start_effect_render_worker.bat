@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 豪斯 AI 家装 - 效果图 Worker
python -m app.workers.effect_render_worker
