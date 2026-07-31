# Blender Worker 运行说明

Blender 高质量渲染采用独立 Worker，不在 FastAPI 请求线程中启动 Blender。

## 本地启动

在 `backend` 目录执行：

```powershell
python -m app.workers.blender_worker
```

只处理一个任务后退出：

```powershell
python -m app.workers.blender_worker --once
```

也可以双击 `backend/start_blender_worker.bat`。

## 运行时发现顺序

1. 环境变量 `BLENDER_EXECUTABLE` 指定的绝对路径。
2. 系统 `PATH` 中的 `blender`。
3. Windows 本地便携目录 `backend/.runtime/blender/blender.exe`。

`.runtime` 已被 Git 忽略，不会把约 400MB 的 Blender 运行时提交到仓库。

## 安全边界

- API 只保存通过 Pydantic 校验的 `SceneDocument`，不接收 Blender Python。
- Worker 只运行仓库内静态脚本 `app/workers/blender_scene_renderer.py`。
- 子进程固定使用 `--background --factory-startup --disable-autoexec --offline-mode`。
- 命令使用参数数组和 `shell=False`，清除 `PYTHONPATH`、`PYTHONHOME`。
- GLB 路径必须解析到允许的本地根目录，远程 URL 和目录穿越会降级为尺寸体块。
- 默认只让 Blender 导入项目内置 `/models/` 资产。员工上传模型在完成身份权限和资产审核前只渲染体块；可信环境可显式设置 `BLENDER_ALLOW_UPLOADED_MODELS=true`。
- 临时结果验证 PNG 签名和大小后，通过 `os.replace` 原子发布。

## 主要配置

- `BLENDER_EXECUTABLE`
- `BLENDER_RENDER_TIMEOUT_SECONDS`，默认 1200 秒
- `BLENDER_RENDER_MAX_MB`，默认 30MB
- `BLENDER_WORKER_POLL_SECONDS`，默认 2 秒
- `BLENDER_WORKER_MAX_ATTEMPTS`，默认 2 次
- `BLENDER_ALLOW_UPLOADED_MODELS`，默认关闭

预览档使用 Eevee 960×540；成片档使用 Cycles 1600×900、128 samples，并按 OptiX、CUDA、CPU 顺序选择设备。
