# 效果图 Worker 运行说明

效果图生成采用数据库持久化队列。FastAPI 的 `POST /api/design/render` 只创建 `effect_render_jobs`，不会加载或调用 Stable Diffusion；独立 Worker 负责认领、续租、调用 SD/ControlNet、发布 PNG 并绑定 `RenderedImage`。

## 首次升级

在 `backend` 目录执行：

```powershell
python -m alembic upgrade head
```

## 启动 Worker

```powershell
python -m app.workers.effect_render_worker
```

只认领一个任务后退出：

```powershell
python -m app.workers.effect_render_worker --once
```

Windows 也可以双击 `backend/start_effect_render_worker.bat`。生产部署必须把 API 与 Worker 作为独立受监管进程，并保证迁移完成后再启动 Worker。

## 状态与恢复

- `queued`、`running` 为活动状态。
- `completed`、`failed`、`dead_letter`、`cancelled`、`provider_unavailable` 为终态。
- 同一设计任务内，`Idempotency-Key` 唯一；同键同输入复取原 Job，同键异输入返回 409。
- Worker 使用 attempt、租约、心跳和总执行截止时间确认所有权。进程退出后，其他 Worker 会回收过期租约；达到次数或截止时间后进入死信。
- 取消会立即清除 Worker 所有权，旧 attempt 无法绑定 `RenderedImage`。
- PNG 先写入 attempt 专属临时文件，再通过 `os.replace` 原子发布。若数据库拒绝陈旧 attempt，Worker 删除该 attempt 的孤立输出。
- 组件通过 `GET /api/design/render/{job_id}` 轮询；重新挂载时通过 `GET /api/design/render?plan_version_id=...` 恢复最新任务。

## 主要配置

- `EFFECT_RENDER_WORKER_POLL_SECONDS`：空闲轮询间隔，默认 1 秒。
- `EFFECT_RENDER_WORKER_MAX_ATTEMPTS`：最大执行次数，默认 2 次。
- `EFFECT_RENDER_WORKER_LEASE_SECONDS`：租约有效期，默认 180 秒。
- `EFFECT_RENDER_WORKER_HEARTBEAT_SECONDS`：心跳间隔，默认 15 秒，必须小于租约及总执行时间。
- `EFFECT_RENDER_WORKER_EXECUTION_TIMEOUT_SECONDS`：任务总执行窗口，默认 900 秒。
- `EFFECT_RENDER_WORKER_RETRY_BASE_SECONDS`：指数退避基数，默认 5 秒。
- `WORKER_PRESENCE_HEARTBEAT_SECONDS`：空闲或繁忙进程都要上报的存活心跳，默认 10 秒。
- `WORKER_READINESS_TIMEOUT_SECONDS`：API 判定 Worker 过期的窗口，默认 45 秒，必须大于存活心跳间隔。

进程启动后会先写入 `worker_heartbeats` 再进入消费循环；首次登记失败时拒绝消费。优雅退出会立即下线，异常退出则在就绪超时后由 `/ready` 返回 503。生产部署使用仓库根目录 `Procfile` 的 `worker-effect-render` 进程类型并开启自动重启。
