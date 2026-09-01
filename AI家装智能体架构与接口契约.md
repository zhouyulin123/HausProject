# AI 家装智能体架构与接口契约

> 状态：阶段 1 基线，由主任务维护
> 基线提交：`5ccdfc8`

## 1. 架构决策

1. 用户看到一个持续的设计项目，而不是多个互不相关的 Agent。
2. 后端使用一个 Design Orchestrator 维护任务状态，需求解析、商品检索、布局、报价、Scene Agent 和渲染是受控工具。
3. 数据库中的 `DesignTask.id` 是设计项目的唯一 `task_id`；前端路由使用同一数值作为 `projectId`，不另造本地项目 ID。
4. 阶段 1 的用户意图 `catalog_design` / `custom_furniture` / `room_reconstruction` 是可切换的工作模式，不是互斥的任务类型。
5. 不向客户端返回模型思维链。只返回用户可理解的计划摘要、工具事件、校验结果和退出原因。

## 2. 身份与并发

- 所有项目 API 必须同时通过 `X-Session-ID` 所有权校验和路径 `task_id` 定位项目。
- 所有场景写入必须携带 `base_version`；版本过期返回 `409`，不得静默覆盖。
- Agent turn 携带客户端生成的 `client_turn_id`；同一 `task_id + client_turn_id` 重复提交必须返回同一结果，不重复调用模型或写场景。
- 任务、图片、对话、方案、场景、报价和运行事件必须可追溯到同一 `task_id`。

## 3. 任务状态

对外统一状态：

| 状态 | 含义 |
| --- | --- |
| `draft` | 已创建，尚未开始分析 |
| `analyzing` | 正在解析意图或空间事实 |
| `waiting_user` | 缺少关键事实，等待用户回答 |
| `ready` | 关键事实已足够，可执行工具 |
| `running` | Agent 或 Worker 正在执行 |
| `waiting_approval` | 等待高风险操作确认 |
| `completed` | 当前目标已通过质量门禁 |
| `needs_human` | 重试耗尽或专业风险需人工接管 |
| `failed` | 可观测失败，有明确退出原因 |
| `cancelled` | 用户或运营主动取消 |

旧状态 `pending` / `waiting_confirm` / `confirmed` / `generating` 在兼容期可保留，但新 API 必须映射为上述统一状态。

## 4. Agent Turn API

新工作台使用：

`POST /api/design/tasks/{task_id}/agent-turns`

请求基线：

```json
{
  "client_turn_id": "uuid-or-stable-client-id",
  "message": "电视柜保留，沙发换小一点",
  "active_mode": "catalog_design",
  "active_room_id": "living-room",
  "scene_id": 12,
  "base_scene_version": 3,
  "selected_instance_id": "sofa-1"
}
```

除 `client_turn_id` 和 `message` 外均可空。场景修改时 `scene_id` 与 `base_scene_version` 必须成对出现。

响应基线：

```json
{
  "task_id": 42,
  "turn_id": 108,
  "state_version": 7,
  "status": "completed",
  "active_mode": "catalog_design",
  "intent": "scene_edit",
  "reply": "已保留电视柜并替换为更小的沙发。",
  "pending_questions": [],
  "events": [],
  "scene_ref": { "scene_id": 12, "version": 4 },
  "exit_reason": "goal_completed"
}
```

约束：

- `status=waiting_user` 时 `pending_questions` 非空，不得同时写入新方案或场景版本。
- `status=completed` 只表示本轮目标完成，不表示整个设计项目不能继续编辑。
- `exit_reason` 只允许受控枚举：`goal_completed` / `missing_facts` / `approval_required` / `retry_exhausted` / `safety_blocked` / `tool_failed` / `cancelled`。
- 保留旧 `POST /api/design/chat` 作为兼容入口，但新工作台不再使用前端模块内存作为对话事实源。

## 5. Agent 事件

每个事件至少包含：

```json
{
  "sequence": 3,
  "type": "tool_completed",
  "node": "validate_scene",
  "status": "completed",
  "source": "deterministic",
  "summary": "场景通过空间硬约束校验",
  "details": {},
  "created_at": "ISO-8601"
}
```

`type` 基线枚举：`state_changed` / `question_created` / `tool_started` / `tool_completed` / `validation_failed` / `scene_committed` / `generation_queued` / `fallback_used` / `human_handoff` / `failed`。

`details` 仅保存可审计参数、产物引用、耗时、用量和错误码；禁止保存密钥、完整隐私图片、模型思维链。

## 6. 空间与 3D 契约

- `RoomModel 1.0` 是感知事实源：归一化 x/z 坐标，可包含多个房间、置信度和待确认项。
- `SceneDocument 1.0` 是当前激活房间的米制编辑快照：单房间、家具实例、门窗和相机。
- `room_model_service.room_model_to_scene` 是从感知事实到可编辑场景的唯一后端转换边界。
- 阶段 1 不修改 `SceneDocument 1.0` 为多房间文档。工作台保存 `active_room_id`，切换房间时加载对应场景。
- `fixedObstacles` 暂作为 RoomModel 只读叠加层和校验输入，不伪装成带 SKU 的 `SceneItem`。
- 单张照片生成的空间必须显示“估算/待校准”；只有 `scale.source=user` 才能显示“已校准”。
- 所有 Agent 场景操作必须经过白名单工具和确定性空间校验后才能提交新版本。

## 7. 商品、报价与数据状态

- 商品硬过滤顺序：启用状态→地区/有效期→尺寸→预算/库存→语义偏好排序。
- 模型不直接生成真实价格。报价必须由确定性服务计算并生成不可变快照。
- 数据和产物统一标识 `real` / `merchant_draft` / `template` / `demo` / `fallback`，前端不得把草稿或降级结果展示为已验证真实数据。

## 8. 阶段 1 合并门禁

1. 从任一入口创建或恢复同一 `task_id`。
2. 刷新页面后可恢复需求、RoomModel、对话和场景版本引用。
3. 缺少预算或尺寸时返回 `waiting_user`，不产生伪完整方案。
4. 场景写入发生版本冲突时可见失败，不静默覆盖。
5. 无效 SKU、报价不一致、场景硬冲突均不能进入 `completed`。
6. 每轮有最大步数、重试次数和明确 `exit_reason`。
7. 前端全量测试与生产构建通过，后端全量测试通过，新增契约有集成测试。

## 9. 兼容与废弃策略

- 阶段 1 不删除 `/customize` / `/upload` / `/chat` / `/results` 和旧同步生成 API。
- 旧页面作为兼容入口或重定向，新功能只在统一工作台继续扩展。
- 废弃接口必须先有调用监控和替代路径，到封闭试点前再清理。
