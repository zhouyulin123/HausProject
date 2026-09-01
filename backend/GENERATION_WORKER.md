# 方案生成 Worker 运行说明

异步方案生成采用数据库持久化队列。FastAPI 默认只写入 `generation_runs`，独立 Worker 负责认领、调用模型并写回结果，因此 API 进程重启不会丢失已入队任务。

## 首次升级

在 `backend` 目录执行：

```powershell
python -m alembic upgrade head
```

## 启动 Worker

```powershell
python -m app.workers.generation_worker
```

只认领一个任务后退出：

```powershell
python -m app.workers.generation_worker --once
```

Windows 也可以双击 `backend/start_generation_worker.bat`。生产部署应把 API 和 Worker 作为两个独立的受监管进程启动，至少保持一个 Worker 实例运行。

## 状态与恢复

- `queued`：等待认领，失败退避期间由 `next_retry_at` 控制再次执行时间。
- `running`：Worker 已持有租约，并按固定间隔续租。
- `completed`、`failed`、`cancelled`：不会再被 Worker 认领的终态。
- Worker 异常退出后，其他 Worker 会回收过期租约；未耗尽次数则重新入队，否则标记失败。
- `Idempotency-Key` 在同一设计任务内唯一，相同键重复请求会返回原运行，不会重复执行。
- 运行中收到取消请求后，Worker 会在步骤写入或最终持久化前停止；最终结果提交与 `completed` 状态处于同一数据库事务。

## 主要配置

- `GENERATION_WORKER_POLL_SECONDS`：空闲轮询间隔，默认 1 秒。
- `GENERATION_WORKER_MAX_ATTEMPTS`：最大执行次数，默认 3 次。
- `GENERATION_WORKER_LEASE_SECONDS`：租约有效期，默认 180 秒。
- `GENERATION_WORKER_HEARTBEAT_SECONDS`：续租间隔，默认 15 秒，必须显著小于租约。
- `GENERATION_WORKER_RETRY_BASE_SECONDS`：指数退避基数，默认 5 秒。
- `GENERATION_INLINE_FALLBACK`：仅用于显式本地调试，默认关闭，生产环境配置为 `true` 会拒绝启动。

接口行为：`POST /api/design/tasks/{task_id}/generate-async` 入队，`GET /api/design/tasks/{task_id}/generation` 查询状态，`POST /api/design/tasks/{task_id}/generation/cancel` 请求取消。
