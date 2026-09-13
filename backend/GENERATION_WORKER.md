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
- `completed`、`failed`、`dead_letter`、`cancelled`、`cost_limit_exceeded`、`provider_unavailable`：不会再被 Worker 认领的终态；其中 `dead_letter` 表示硬截止时间到期或可重试执行已耗尽，后两者分别表示成本门禁或供应商熔断已将任务转人工确认。
- 首次认领会固定整个运行的 `execution_deadline_at`。心跳只能把租约续到该时间，不能延长总执行窗口；后续 attempt 也沿用同一截止时间。
- Worker 异常退出后，其他 Worker 会回收过期租约；仍有次数且能在截止时间前退避则重新入队，否则进入 `dead_letter`，对应设计任务状态为 `failed`。
- `Idempotency-Key` 在同一设计任务内唯一，相同键重复请求会返回原运行，不会重复执行。
- 运行中收到取消请求后，Worker 会在步骤写入或最终持久化前停止；最终结果提交与 `completed` 状态处于同一数据库事务。
- 每次文本模型调用前会按输入字节上界和最大输出 token 保守估算，并在数据库中原子预留成本。账本按设计任务聚合，后续重试或新运行不会重置上限。
- 价格配置缺失或余额不足时，供应商请求不会发出，也不会伪装成模板生成成功。运行会写入 `cost_guard` 事件并转人工处理。
- 模型供应商熔断状态按 `LLM_PROVIDER_KEY` 持久化，多个 Worker 通过数据库行锁共享失败计数。超时、连接失败、429 和 5xx 才计数；成本门禁、取消、业务校验、JSON 解析与程序错误不计数。
- 达到阈值后进入 `open`，冷却期的任务会在发出供应商请求前写入 `provider_circuit` 事件并显式转人工。冷却后仅一个带租约的半开探针可调用；成功关闭熔断，失败重新开启。

## 主要配置

- `GENERATION_WORKER_POLL_SECONDS`：空闲轮询间隔，默认 1 秒。
- `GENERATION_WORKER_MAX_ATTEMPTS`：最大执行次数，默认 3 次。
- `GENERATION_WORKER_LEASE_SECONDS`：租约有效期，默认 180 秒。
- `GENERATION_WORKER_HEARTBEAT_SECONDS`：续租间隔，默认 15 秒，必须显著小于租约。
- `GENERATION_WORKER_EXECUTION_TIMEOUT_SECONDS`：单个持久化运行的总执行窗口，默认 900 秒，范围 30–7200 秒；生产必须为正值。
- `GENERATION_WORKER_RETRY_BASE_SECONDS`：指数退避基数，默认 5 秒。
- `GENERATION_TASK_COST_LIMIT_CNY`：单个设计任务的文本模型保守预留成本上限，默认 1 元，范围 `(0, 1000]`。
- `LLM_INPUT_PRICE_PER_MTOK` / `LLM_OUTPUT_PRICE_PER_MTOK`：每百万 token 人民币单价。生产环境启用 LLM 时必填；Worker 运行期缺失也会闭合阻断调用。
- `LLM_PROVIDER_KEY`：稳定的供应商/路由标识，默认 `primary-llm`；更换模型但共用同一故障域时应保持不变。
- `PROVIDER_CIRCUIT_FAILURE_THRESHOLD`：连续可用性失败开启熔断的阈值，默认 3，范围 1–20。
- `PROVIDER_CIRCUIT_COOLDOWN_SECONDS`：开路冷却时间，默认 60 秒，范围 5–3600 秒。
- `PROVIDER_CIRCUIT_PROBE_LEASE_SECONDS`：半开单探针租约，默认 30 秒，范围 5–300 秒。
- `GENERATION_INLINE_FALLBACK`：仅用于显式本地调试，默认关闭，生产环境配置为 `true` 会拒绝启动。
- `WORKER_PRESENCE_HEARTBEAT_SECONDS`：空闲或繁忙进程都要上报的存活心跳，默认 10 秒。
- `WORKER_READINESS_TIMEOUT_SECONDS`：API 判定 Worker 过期的窗口，默认 45 秒，必须大于存活心跳间隔。

接口行为：`POST /api/design/tasks/{task_id}/generate-async` 入队，`GET /api/design/tasks/{task_id}/generation` 查询状态（含 `execution_deadline_at`、`dead_lettered_at`、`cost_cny`、`cost_reserved_cny` 与 `cost_limit_cny`），`POST /api/design/tasks/{task_id}/generation/cancel` 请求取消。

进程启动后会先写入 `worker_heartbeats` 再进入消费循环；首次登记失败时拒绝消费。优雅退出会立即下线，异常退出则在 `WORKER_READINESS_TIMEOUT_SECONDS` 后被 `/ready` 判为过期。生产部署使用仓库根目录 `Procfile` 的 `worker-generation` 进程类型并开启自动重启。
