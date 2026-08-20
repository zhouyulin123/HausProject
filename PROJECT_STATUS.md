# 项目开发状态记录

## 2026-08-19 空间事实模型 M1 + 自动布局 M2 完成

按外部专家评审的 M1/M2 里程碑落地，主方向「户型结构化理解 → 自动生成可编辑 3D 布局」。

### M1 统一空间事实模型 RoomModel

- `schemas/room_model.py`：RoomModel Schema（归一化坐标 0~1 + confidence + requiresConfirmation + rooms/walls/doors/windows/fixedObstacles/existingFurniture/scale）。
- VL 结构化输出：`llm_service.analyze_room_model`，Qwen3-VL 输出房间多边形/门窗/置信度，绝对尺寸不猜（置 null + requiresConfirmation）。
- `room_model_service`：`room_model_to_scene`（归一化→米制居中、门窗映射、默认尺寸兜底）+ `apply_calibration`（用户真实尺寸写回，scale=user）。
- 尺寸校准：`PUT /api/upload/images/{id}/room-model` + 前端 `RoomCalibration` 内联卡片。
- 前端 3D：`buildSceneDocument` 消费 RoomModel 校准尺寸（替换 `ROOM_SIZE` 硬编码兜底），`useRoomModelStore` 跨页透传。

### M2 自动布局智能体

- 几何工具提取为公共模块 `scene_geometry.py`（scene_service 与布局引擎共用）。
- 确定性生成器 `layout_generator.generate_layouts`：沙发靠后墙（居中/偏左/偏右 3 变体）、电视柜正对靠前墙、茶几在前、地毯/灯具/休闲椅/床/餐桌，其余沿墙排布；商品真实尺寸。
- 确定性评分器 `layout_evaluator`：越界(20)/碰撞(15)/门窗遮挡(25)/观看距离(10)/尺寸过大(5)，`HARD_FAIL_CODES` 任一出现即不合格。
- 确定性修复器 `layout_repair`：越界夹回、碰撞候选偏移避让、遮挡沿墙移开、观看距离调电视柜纵深；generate→evaluate→repair→重新评估，最多 3 轮。
- 桥接 `layout_service` + 幂等接口 `POST /api/design/plan-versions/{id}/auto-layout`（场景存在即返回）→ 写 `design_scenes`（source=auto_layout）；前端 3D 打开优先调它，失败回退本地构建。
- **20 例标准客厅验收评测** `backend/evals/`：覆盖尺寸（3.6~5.8m 宽）、家具组合（三件套/L型/软装/边柜/满配）、门窗情况；当前 100% 通过、平均 100 分，报告在 `evals/reports/living_room_eval.md`。

### 验证

- 后端 **146 passed**（RoomModel 10 + 布局生成/评估/修复 16 + auto-layout 2 + 评测 4 + 其余回归）。
- 前端 **38 passed** + tsc + vite build 通过。

### 关键决策

- RoomModel=感知层（归一化事实），SceneDocument=生成层（米制场景）；`room_model_to_scene` 只做几何映射不摆家具。
- 布局质量评估纯确定性（无 LLM）；硬错误即不合格、软问题排序选优；repair 以"issues 非空即修复"为目标而非仅保合格线。
- auto-layout 幂等，场景已存在不重复生成；前端降级链：auto-layout → 本地构建。

### 下一步（M3）

1. 评测体系扩展：30-50 条跨空间评测集（卧室/餐厅/书房）+ 需求提取/约束遵守/预算偏差等指标。
2. 生成元数据落库（模型/Prompt/输入/输出/评分/成本），用用户修改行为反推失败类型。
3. 多空间布局规则深化（卧室/餐厅专用摆位）。

## 2026-08-19 M3 评测体系第一批：跨空间布局评测 + 多空间生成规则

### 生成器多空间规则（`layout_generator`）

- 卧室：床靠后墙居中 / 靠侧墙（变体），床头柜贴床短边两侧，衣柜在床对面墙依次排布面向床；卧室里的梳妆台（书桌类）走沿墙排布避免与床重叠。
- 餐厅：餐桌居中，餐椅围绕四边（上/下/左/右 + 第二排），面向餐桌。
- 书房：书桌靠后墙 + 书椅在前（旋转面向桌子）。

### 跨空间评测集与 runner

- `evals/cases/base.py`：通用 `RoomCase`（含 group 分组）；`living_room.py` 改用 base 保持兼容。
- `evals/cases/bedroom.py`（8 例）/ `dining_room.py`（6 例）/ `study.py`（4 例）：覆盖尺寸、家具组合、儿童房/双衣柜/6 椅等变体。
- `evals/run_layout_eval.py`：`python -m evals.run_layout_eval` 按空间分组跑全部 38 例，输出通过率/平均分/失败原因分布，报告写 `evals/reports/layout_eval.md`。
- `tests/integration/test_layout_eval.py`：断言 ≥30 例、总通过率 ≥90%、各空间通过率 ≥80%、平均分 ≥70。

### 结果

- **38 例（客厅 20 + 卧室 8 + 餐厅 6 + 书房 4）全部 100 分通过**。

### 踩坑

- 循环变量 `for index, ... in enumerate` 覆盖 `place` 的 `nonlocal index`，导致同 SKU 多件家具 instanceId 冲突 → 循环变量全部改名（table_index/cabinet_index/chair_index）。
- 卧室衣柜（category 柜子）被客厅 TV 分支误当电视柜放前墙，随后衣柜分支再放一次 → 双衣柜碰撞 → TV 分支限定 `if tv and sofa`。

### 验证

- 后端 **150 passed**（新增 test_layout_eval.py 4 项）。

## 2026-08-19 M3 第二批：布局生成元数据落库

- 新增 `layout_runs` 表（`LayoutRun` 模型 + Alembic 迁移 `a1f3c5e7b9d2`）：plan_version_id、scene_version_id、room_name/宽深、furniture_count、candidate_count、**best_score、best_valid、issue_codes、duration_ms、source、created_at**。
- `layout_service.record_layout_run`：写入一次布局生成的输入摘要 + 最优评分 + 问题分布 + 耗时。
- auto-layout 路由集成：create_scene 成功后记录（带 scene_version_id），幂等返回不重复记录。
- `test_auto_layout_api` 新增元数据断言（best_score=100 / furniture_count=3 / issue_codes=[] / source=auto_layout / scene_version_id 非空）。

### 用途

每次 auto-layout 的质量历史可查询；配合用户对场景的手动修改，后续可反推"布局失败类型"（用户动得多的区域即薄弱点）。

### 验证

- 后端 **151 passed**。

## 2026-08-19 M3 第三批：生成元数据落库 + 需求级指标 + 修改反推

补齐 M3 剩余三项，让评测体系从「布局质量」扩展到「方案生成质量 + 成本 + 需求级指标 + 用户修改闭环」。

### 生成元数据落库（generation_runs 扩展）

- `GenerationRun` 新增 6 列：`model` / `prompt_snapshot`（截断 8000 字）/ `input_snapshot`（需求+画像上下文）/ `output_snapshot`（方案名/风格/预算/评分/家具数摘要）/ `usage_json`（token 用量）/ `cost_cny`（估算成本）。迁移 `b2e4d6f8a0c1`（down_revision=`a1f3c5e7b9d2`，head 唯一）。
- `llm_service._chat_json` 捕获 token usage；`generate_plans` 成功后把模型/Prompt/输入/用量/成本写入 `last_generation_meta()`，每次调用前先清空避免降级残留旧值。
- `estimate_cost_cny` 纯函数：按 `LLM_INPUT_PRICE_PER_MTOK` / `LLM_OUTPUT_PRICE_PER_MTOK`（可选配置，默认 None）估算成本；没配单价只记用量不记成本。
- `generation_run_service.record_generation_meta`：把 meta 写回 `generation_runs`；`tasks._execute_generation` 通过 `on_meta` 回调在后台执行器落库（同步 `/generate` 不建 run，不落库）。
- `layout_scores_for_task`：聚合某任务所有 `layout_runs` 的平均分/通过率/问题分布，把「布局评分」挂到 generation 维度可查询。

### 需求级指标（可选 eval，需 LLM，不纳入 CI）

- `evals/cases/requirement_cases.py`：5 例需求提取 + 4 例约束遵守 + 4 例预算偏差 ground truth。
- `evals/run_requirement_eval.py`（`python -m evals.run_requirement_eval [--skip-llm]`）：
  - 需求提取准确率：字段级确定性比对（space_type/style/area/budget/constraints/custom_projects）。
  - 预算偏差率：方案报价相对预算范围的确定性偏差。
  - 约束遵守率：`llm_service.judge_plan_compliance` LLM judge，与人工标注对账并报告 judge 准确率。
- 报告写 `evals/reports/requirement_eval.md`。

### 用户修改行为反推失败类型

- `layout_service.diff_scene_items`：对比两个场景文档，逐实例输出位移/旋转/增删。
- `layout_service.summarize_edits`：聚合成「改动最多的家具类别 = 布局薄弱点」信号。
- `layout_service.analyze_manual_edits`：取场景的 `auto_layout` 初稿 vs 最新 `manual` 版本，反推失败类型（用户动得多的区域即引擎弱项）。

### 验证

- 后端 **170 passed**（新增 19 项：generation meta 2 + 成本估算 3 + 需求指标 8 + 修改反推 6；迁移断言扩展 generation_runs 新列）。
- Windows 下全量跑建议用全新 `--basetemp`（`tmp_path` 权限 flaky，非代码问题，见 2026-08-17 环境备注）。


## 2026-08-18 AI 模型环境变量统一

- 文本模型配置统一为提供商无关的 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，不再让业务代码绑定 DeepSeek 命名。
- 视觉模型配置统一为 `VL_API_KEY` / `VL_BASE_URL` / `VL_MODEL` / `VL_REASONING_MODEL`。
- 保留旧 `DEEPSEEK_*`、`VL_API_KEY_BASE_URL`、`VL_MODEL1/2` 的读取兼容，方便其他部署环境平滑迁移。
- 本地 Stable Diffusion、ControlNet 与 Hugging Face 缓存配置显式归入 `.env`，`.env.example` 按用途分组整理。
- 配置代码中的机器专属 Hugging Face 缓存默认路径改为相对目录 `./hf_cache`。

### 验证

- 配置兼容与 AI 工作流相关单测：`10 passed`；后端全量测试：`114 passed`。
- 当前有效模型配置检查通过，Chat/VL 均继续指向 SiliconFlow，模型名称与迁移前一致。

## 2026-08-18 Chat 体验 P0 修复

- **动态开场白**：去掉 mockChat.initialMessages 的固定文本；新增 `lib/openingMessage.buildOpeningMessage`，根据 `useRequirementStore` 的真实数据（户型、面积、风格、预算、家庭情况）拼一段引用具体信息的开场白，并按"最该先确认什么"挑一个针对性的开场问题。
- **去掉 mockChat 降级**：`designApi.sendChatMessage` 失败时不再回退到 `getAiReply`（关键词匹配的假回复），改为返回"AI 服务暂时不可用，请稍后再试。"——假回复比"暂不可用"更毁信任。
- 验证：前端 `35 passed`（新增 6 项），tsc + vite build 通过。

### 用户反馈来源

- 之前 chat 页"开场白每次一样、AI 回复不像 AI"是 `mockChat.getAiReply` 的关键词规则在前端降级兜底；现在 catch 块不再回退 mock。

## 2026-08-18 3D 场景继承

- 修复 P0 的遗留缺口：精修后新方案（新 planVersionId）没有 3D 场景的问题。
- `plan_refine_service.refine_plan_version`：精修写入新版本后，若旧方案已有 3D 场景，把场景的 `plan_version_id` 归属移到新版本，保留用户的家具布局。

### 验证

- 后端全量测试：`112 passed`（新增场景继承 1 项）。

## 2026-08-18 画像接入业务流程（P1 第 3、4 步）

- 画像**写入**（登录用户，不阻断主流程）：
  - `confirm_requirement`：确认需求后从结构化需求提取画像。
  - `refine_plan_version`：精修后从修改指令提取画像（学习预算敏感、材质偏好等信号）。
- 画像**读取**：
  - `_execute_generation`：生成方案前读画像，注入 `requirement["profile_context"]`。
  - `_PLAN_SYSTEM` 增加指令：方案必须贴合画像中的预算、风格、家庭结构、生活方式与软性偏好。
- P1 闭环达成：确认需求/精修 → 存画像 → 下次生成方案 → 用画像。

### 验证

- 后端全量测试：`111 passed`。

### 说明

- 「匿名画像合并」暂不需要：匿名阶段（task.user_id 为空）不提取画像，登录后自然无匿名画像可合并；未来若支持匿名画像挂 session，再补合并逻辑。

## 2026-08-18 用户画像存储基础（P1 第 1、2 步）

- 新增 `user_profiles` 表（迁移 `21b0bc4721d4`，已应用到 MySQL）：
  - 关键维度用列：`budget_min` / `budget_max` / `preferred_styles`（JSON）。
  - 扩展维度用 `profile_json`（JSON 兜底，避免频繁迁移）。
  - `User` 增加 `profile` 一对一关系。
- `llm_service.extract_profile`：从文本（需求/对话/修改指令）提取装修画像。
- `profile_service`：
  - `get_or_create_profile` / `merge_profile`（增量合并：标量覆盖、列表去重合并、预算覆盖）。
  - `extract_and_merge`（LLM 提取 + 合并，LLM 不可用时静默跳过不阻断主流程）。
  - `build_profile_context`（画像转 LLM 上下文文本）。

### 验证

- 后端全量测试：`111 passed`（新增 profile_service 5 项）。
- 迁移 `alembic current`：`21b0bc4721d4 (head)`。

### 下一步（P1 第 3、4 步）

- 在 `confirm_requirement`、`refine_plan` 节点挂画像提取。
- 在 `generate_plans`、`chat_reply` 里注入画像上下文。
- 登录时把匿名画像合并进账号。

## 2026-08-18 方案级 AI 精修（P0）

- 新增「方案级自然语言修改 Agent」，让 AI 从「一次性出 3 套」升级为「对话式打磨」：
  - `llm_service.refine_plan`：在现有方案上按指令精准修改（换风格/换家具/调配色/调预算），返回修改后完整方案 + 一句话说明。
  - `agents/plan_refine_agent.py`：复用 Scene Agent 的 `plan→execute→validate` 三节点模式，模型做语义修改，`catalog_service` 确定性回填商品 SKU 与报价，质量门禁校验。
  - `services/plan_refine_service.py`：编排精修，替换目标方案、保留其余方案，写入新的不可变 plan version（generator=refine）。
  - 路由 `POST /api/design/tasks/{task_id}/plans/{plan_id}/refine`。
- 方案 payload 统一带 `task_id`（result / 我的方案 / refine 返回），前端可精确知道方案所属任务。
- 前端 `DesignDetailPage` 顶部新增「AI 修改方案」输入框，回车或点「应用修改」即生效；修改后详情页立即切换到新版本方案。

### 验证

- 后端全量测试：`106 passed`（新增 refine agent 3 项、refine service 2 项、路由断言）。
- 前端全量测试：`29 passed`，tsc 与 vite 构建通过。

### 已知局限（后续）

- 修改不继承旧版本的 3D 场景（refine 产生新 planVersionId，旧场景仍挂在旧版本上），后续可做「场景继承或重置提示」。
- 预算达标目前靠 LLM 尽量满足（换便宜商品/减工程量），未做强校验。

## 2026-08-18 报价通知角标 + 用户管理拆分

- 厂家报价通知角标：
  - 后端新增 `GET /api/orders/unread-count`（需登录）+ `order_service.unread_quote_count`（客户待选择报价总数）。
  - 前端 `Header` 对普通用户每 30 秒轮询，在「我的订单」菜单显示红点角标（>99 显示 99+）。
- 用户管理从商品库页拆出：
  - 新增 `RequireAdmin` 路由守卫 + 独立页面 `AdminUsersPage`（路由 `/admin/users`，仅管理员）。
  - `AdminPage` 移除「用户管理」Tab，恢复为纯厂家功能（成品家具/定制报价/店铺设置）。
  - `Header` 管理员额外显示「用户管理」入口。

### 验证

- 后端全量测试：`101 passed`（新增 unread_quote_count 1 项 + 路由断言）。
- 前端全量测试：`29 passed`，tsc 与 vite 构建通过。

## 2026-08-18 详情页后端兜底拉取

- 补齐「我的方案」闭环的最后一块：详情页本地无缓存时向后端按版本兜底。
- 后端新增 `GET /api/design/plan-versions/{plan_version_id}`（需登录）：
  - `design_version_service.get_plan_version_for_user` 按方案版本 ID 查询并校验归属（`task.user_id`），杜绝越权。
  - 返回方案快照（含 `planVersionId` / `planKey`）。
- 前端 `DesignDetailPage`：本地 `generatedPlans` 找不到方案且 id 为数字时，向后端拉取兜底；拉取中显示加载态。
- 现在登录用户的方案可跨设备直接打开 `/design/{planVersionId}`，不再依赖本地缓存。

### 验证

- 后端全量测试：`100 passed`（新增 get_plan_version_for_user 1 项 + 路由断言）。
- 前端全量测试：`29 passed`，tsc 与 vite 构建通过。

## 2026-08-17 详情页按 planVersionId 定位

- 修复多任务同名方案（plan-a/b/c）串号问题：
  - `SavedDesign` 类型新增 `planVersionId?`；「我的方案」后端方案跳转改为 `/design/{planVersionId}`。
  - `DesignDetailPage` 匹配逻辑优先按 `planVersionId`（数字 id）精确定位，找不到再回退 `plan.id`（本地方案/结果页）。
- 验证：前端 `29 passed`，tsc 与 vite 构建通过。

### 已知局限

- 详情页仍依赖 `generatedPlans`（本地持久化）；跨设备直接访问 `/design/{planVersionId}` 时无本地缓存会找不到方案，需后续加「按 planVersionId 拉取方案」接口。

## 2026-08-17 我的方案后端化

- 后端新增 `GET /api/design/tasks/mine`（需登录）：返回当前用户的设计任务，每个任务附带最新版本的三套方案快照（含 `planVersionId` / `planKey`）。
  - `design_version_service.list_user_designs` 复用 `get_latest_revision`，只返回有方案版本的任务。
- 前端 `MyDesignsPage` 登录后从后端拉取历史方案，注入 `generatedPlans` 供详情页查看，并生成 `SavedDesign` 摘要展示；未登录仍回退本地 localStorage。
  - 后端方案（id 前缀 `server-`）隐藏本地「收藏/删除」按钮，避免误导（删除后端方案需后续做删除接口）。
- `designApi` 新增 `fetchMyDesigns`（Bearer 鉴权 + decorate 方案封面）。

### 验证

- 后端全量测试：`99 passed`（新增 list_user_designs 1 项 + 路由断言）。
- 前端全量测试：`29 passed`，tsc 与 vite 构建通过。

### 已知局限

- 方案详情跳转仍用 `plan.id`（plan-a/b/c），多个任务的同名方案可能冲突；后续可改为按 `planVersionId` 定位详情。
- 「我的方案」删除/收藏目前仅对本地方案生效；后端方案的删除与收藏需补接口。

## 2026-08-17 登录与订单池优化一轮

- 订单列表返回报价数 + 客户手机号脱敏：
  - `list_customer_orders` 返回 `pending_quote_count`；`list_order_pool` 返回 `pending_quote_count` 且 `customer_name` 脱敏（`138****0080`）。
- 登录时合并匿名会话：`login` 接口接收可选 `session_id`，`auth_service.merge_anonymous_session` 把该会话的设计任务与图片归属到账号（为后续「我的方案」后端化铺路）。
- 前端：
  - `LoginPage` 登录成功后回跳原页面（读取 `location.state.from`）。
  - `orderApi` / `adminApi` 在 401 时自动清登录态（`useAuthStore.logout()`），token 失效不再持续报错。
  - `authApi.login` 携带当前匿名会话 id。
  - 订单页展示报价数：我的订单「N 个报价待选择」，工作台「已有 N 人报价」。

### 验证

- 后端全量测试：`98 passed`（新增 merge 1 项、订单报价数/脱敏 2 项）。
- 前端全量测试：`29 passed`，tsc 与 vite 构建通过。

### 环境备注

- Windows 下 pytest 的 `tmp_path` 临时目录受 workbuddy safe-delete shim 影响权限不稳定，全量跑建议每次用全新 `--basetemp` 目录（或先清理），否则 blender 相关测试会报 WinError 5。非代码问题。

## 2026-08-17 登录与订单池（厂家接单）

- 新增手机号验证码登录/注册二合一（Mock 阶段固定验证码 `123456`，开发环境后端日志打印并在响应返回 `dev_code`）：
  - `users` 表新增 `role`（customer/factory/admin）、`phone_verified`、`last_login_at`。
  - 新增 `sms_codes` 表 + `auth_service`（验证码生成/60s 限流/5 分钟过期/一次性消费、登录即注册、JWT 签发解析）。
  - 接口：`POST /api/auth/send-code`、`POST /api/auth/login`、`GET /api/auth/me`。
- 新增订单池（多方报价比价）：
  - `orders`（订单意向，支持绑定方案 `plan` / 纯需求 `requirement`）+ `order_quotes`（厂家报价）两张表。
  - 接口：`POST /api/orders`、`GET /api/orders/mine`、`GET /api/orders`、`GET /api/orders/{id}`、`POST /api/orders/{id}/quotes`、`POST /api/orders/{id}/accept`、`POST /api/orders/{id}/close`。
  - 用户接受某报价后订单锁定（`assigned`），其余报价自动 `rejected`。
- 新增权限依赖：`get_current_user`（Bearer JWT）、`require_factory`（厂家/管理员）、`require_admin`。
- 给 `products` / `shop` / `customers` 全部写接口加 `require_factory`，堵住裸奔写接口。
- 新增管理员接口：`GET /api/admin/users`、`PATCH /api/admin/users/{id}/role`。
- 新增 `backend/set_admin.py`：首次部署时自举管理员账号（`python set_admin.py <手机号>`）。
- 前端：
  - 新增 `useAuthStore` + `authApi` + `orderApi` + `adminApi`。
  - `LoginPage` 改为手机号+验证码登录/注册（去邮箱/密码/微信 mock）。
  - 新增路由守卫 `RequireAuth` / `RequireFactory`；`/workspace` `/customers` `/admin` 需厂家权限，`/orders` 需登录。
  - `Header` 按角色显示导航；登录后显示昵称+角色徽章+退出。
  - 新增 `OrdersPage`（用户订单）、`WorkspacePage`（厂家工作台/订单池）、`AdminPage` 用户管理 Tab。
  - `DesignDetailPage` 新增「发布订单意向」按钮（绑定方案或纯需求）。
- 迁移：`e7f8a9b0c1d2`（head），已应用到 MySQL。

### 验证

- 后端全量测试：`95 passed`（新增 auth 7 项、订单 8 项、路由与迁移断言扩展）。
- 前端全量测试：`29 passed`（新增 useAuthStore 3 项）。
- TypeScript 检查与 Vite 生产构建通过。
- MySQL `alembic current`：`e7f8a9b0c1d2 (head)`，`alembic check` 无漂移。

### 备注与后续

- 短信为 Mock 阶段，生产需接短信服务商（替换 `auth_service._send_sms`）。
- 首个管理员账号需运行 `python set_admin.py <手机号>` 自举，之后在 `/admin` 用户管理中授权。
- 本机开发/测试需用 `D:/software/py314/python.exe`（项目依赖装在 Python 3.14），默认 `python` 指向 workbuddy 3.13.12 无依赖。
- 下一步候选：把匿名会话方案在登录后合并到账号、订单与厂家报价通知、真实短信服务商接入。

## 2026-08-17 最新代码同步说明

- 当前稳定代码基线：`ac357e5 feat: 建立隔离Blender Worker高质量渲染链路`。
- 当前 GitHub 仓库：`zhouyulin123/HausProject`，功能代码已经与远端 `main` 对齐。
- 客户侧完整主链路已经具备：
  - AI 需求理解、户型/图片分析、方案生成、家具推荐和规则化报价。
  - 风格案例真实图片轮播、方案详情、效果图生成和 PDF 提案导出。
  - Web 3D 场景编辑、商品 GLB 模型、场景不可变版本和自动保存。
  - Scene Agent 自然语言空间调整，以及越界、碰撞和门口动线安全校验。
  - 独立 Blender Worker，支持 Eevee 预览、Cycles 成片、任务轮询和 PNG 下载。
- 最近一次完整验证基线：后端 `81 passed`，前端 `26 passed`，TypeScript 与 Vite 生产构建通过；RTX 5060 已真实验证 Blender `OPTIX` 渲染。
- 数据库最新迁移版本：`d4e6f8a0b2c4 (head)`。
- 下一主施工方向：材质库、HDRI/灯光预设、多相机成片清单，以及员工登录、模型审核和共享 Worker 队列。

### 本地运行补充

- Web 服务使用项目根目录 `startHaus.bat` 启动；旧的乱码中文启动脚本已经移除。
- Blender Worker 使用 `backend/start_blender_worker.bat` 单独启动；API 服务与 Worker 应保持为两个独立进程。
- Blender 便携运行时、渲染缓存和成片文件位于 Git 忽略目录，不上传到代码仓库。
- `case_image/` 中 8 种风格、每种 3 张的 24 张原始案例图已纳入仓库，前端优化版仍用于网页实际加载。
- 真实 `.env` 只保存在部署机器；仓库使用 `.env.example` 维护完整变量清单，避免 API Key 和数据库凭据进入 Git 历史。

## 2026-07-31 Blender Worker 高质量渲染第五批

- 新增与不可变 `DesignSceneVersion` 绑定的 `blender_render_jobs`：
  - `queued / running / completed / failed` 状态、真实进度、尝试次数。
  - Worker ID、租约过期、崩溃恢复和同版本/同档位幂等去重。
  - 预览档与成片档独立保存，不会因客户继续编辑场景而改变已提交快照。
- 新增客户归属隔离的渲染接口：
  - `POST /api/design/scenes/{scene_id}/render-jobs`
  - `GET /api/design/scenes/{scene_id}/render-jobs/{job_id}`
  - 过期场景版本返回 `409`；同会话每小时最多创建 10 个新渲染作业。
- 新增独立 Blender Worker：
  - FastAPI 只入库作业，不在请求线程中运行 Blender。
  - Blender 调用固定使用后台、恢复出厂、禁用自动脚本、离线和 Python 异常退出码参数。
  - 命令使用 `shell=False`，清除 Python 注入环境，客户输入不能成为脚本或命令参数。
  - 超时后终止进程；Worker 崩溃后通过数据库租约有限重试。
- 新增声明式 SceneDocument → Blender 渲染器：
  - 构建房间地面、带门窗洞口的墙体、商品 GLB/安全体块、室内相机和灯光。
  - 远程模型 URL、目录穿越和非 GLB 资产全部拒绝。
  - 默认只导入项目内置模型；员工上传模型在权限和资产审核完成前降级为体块。
  - PNG 产物经过签名和大小校验后原子发布，并自动进入原有效果图/PDF 数据链路。
- 前端 3D 编辑器新增 Blender 高质量渲染区：
  - 可选择 Eevee 快速预览或 Cycles 成片。
  - 自动轮询排队/运行进度，完成后直接展示和下载 PNG。
  - 渲染绑定明确的场景版本，保存失败、冲突和限流均有独立反馈。
- 本机安装 Blender 5.2.0 LTS 便携运行时到 Git 忽略目录 `backend/.runtime/blender`。

### 验证

- Blender 5.2.0 LTS 启动：通过
- Eevee 真实预览任务：完成并生成 PNG
- Cycles 真实成片任务：完成，RTX 5060 成功选择 `OPTIX`
- MySQL 实际迁移到 `d4e6f8a0b2c4 (head)`：通过
- 后端全量测试：`81 passed`
- 前端全量测试：`26 passed`
- 前端覆盖率：语句 63.25%、分支 47.58%、函数 65.65%、行 65.57%
- TypeScript 与 Vite 生产构建：通过
- 浏览器实测：3D 布局正确展示 Eevee/Cycles 渲染入口，演示方案权限状态正确，控制台无错误

### 下一施工批次

1. 建立材质库和 HDRI/灯光预设，让商品材质、墙地面和风格方案直接驱动 Blender 成片质量。
2. 增加多相机机位、缩略图和一套场景多张成片的 artifact manifest。
3. 完成员工登录、模型审核和共享队列后，再开放上传 GLB 的 Blender 导入权限。

## 2026-07-31 Scene Agent 空间操作第四批

- 新增基于 LangGraph 的三节点 Scene Agent 工作流：
  - `plan_operations`：付费模型把客户自然语言转换成结构化操作。
  - `execute_tools`：确定性白名单工具执行操作，不运行模型生成的代码。
  - `validate_space`：写入前检查 SKU、越界、碰撞和门口通行动线。
- 新增四类严格 Pydantic 鉴别联合命令：
  - `move`：移动已有家具到绝对米制 X/Z 坐标。
  - `rotate`：设置已有家具的绝对 Y 轴弧度。
  - `remove`：删除已有家具实例。
  - `add`：只能从有效商品 SKU 新增，并由商品毫米尺寸生成真实场景尺寸。
- 新增 `POST /api/design/scenes/{scene_id}/agent-command`：
  - 沿用匿名会话归属隔离和场景乐观版本号。
  - 模型调用前先拒绝过期版本，避免明显的付费浪费。
  - 同一匿名会话使用每分钟 6 次的滑动窗口限流，超限返回 `429` 和 `Retry-After`。
  - 模型返回后重新加锁复核版本，防止并发页面静默覆盖。
  - AI 建议只有通过空间安全门禁后才生成 `scene_agent` 不可变新版本。
- 空间语义校验从“中心点是否在房间”升级为：
  - 旋转后完整家具占地是否越界。
  - 家具 OBB 占地与垂直范围的真实碰撞检测。
  - 门与通道内侧 0.9 米净空是否被家具占用。
  - 地毯、窗帘作为明确的非阻挡类别，不产生虚假家具碰撞。
- Scene Agent 模型提示明确世界坐标和厘米到米的转换；空操作会有限重试一次，仍不合规则明确失败。
- 前端 3D 编辑器新增 Scene Agent 输入区、执行状态和安全拒绝反馈：
  - 正式方案会先保存客户手动修改，再基于最新版本执行 AI 命令。
  - 演示方案禁用云端写入，不伪装为真实 Agent 成功。
  - 409 冲突、422 空间阻挡与模型不可用均有不同反馈。

### 验证

- 后端全量测试：`69 passed`
- 前端全量测试：`25 passed`
- 前端覆盖率：语句 63.06%、分支 47.58%、函数 64.94%、行 65.37%
- TypeScript 与 Vite 生产构建：通过
- 真实付费模型测试：“沙发向左移动 30 厘米”正确生成 `x: 0 → -0.3` 的白名单操作
- 浏览器实测：Scene Agent 区域、正式/演示状态、响应式表单正常，控制台无 error / warning

### 下一施工批次

1. 建立隔离的 Blender Worker 作业协议，将 `SceneDocument` 转换为高质量渲染任务，禁止客户输入直接进入 Blender Python。
2. 增加全房间网格寻路与多门洞连通性分析，把“门口净空”升级为完整主通行动线评分。
3. 把后台写接口和 Worker 管理纳入员工身份、角色权限和共享式限流。

## 2026-07-31 商品 GLB 模型链路第三批

- 商品库新增 3D 资产契约：GLB URL、`missing / ready / failed` 状态、毫米制宽高深、授权和来源信息。
- 新增迁移 `b7d9e1f3a5c8`，并已在当前 MySQL 实际升级：
  - 当前 22 件商品中 19 件已绑定项目内置演示模型。
  - 新数据库灌入种子商品时也会得到一致的模型元数据。
- 新增受控 GLB 上传接口 `POST /api/products/{product_id}/model`：
  - 只接受 `.glb`、允许的 MIME 与完整 glTF 2.0 二进制容器。
  - 校验空文件、25MB 上限、魔数、版本、声明长度、JSON 块和资产版本。
  - 服务端使用随机文件名落盘，客户端文件名不能控制存储路径。
- 顺带修复原商品图片上传接口未校验内容的问题，现与户型图片共用大小、MIME、签名和扩展名校验。
- 商品后台可维护模型三维尺寸、授权和来源，选择 GLB 后会在保存商品后完成绑定；商品列表显示 `3D` 状态。
- 新增 9 个轻量参数化 GLB 示例资产及可重复生成脚本，覆盖沙发、椅子、茶几、柜子、灯、地毯、床、书桌和餐桌。
- Web 3D 编辑器按 SKU 加载 GLB，自动把模型包围盒归一化到真实商品尺寸；单件模型加载失败会明确降级为尺寸体块，不会拖垮整个场景。
- 规则布局优先使用商品模型的真实宽高深，布局、碰撞边界和视觉模型保持同一尺度。

### 验证

- 后端全量测试：`57 passed`
- 前端全量测试：`24 passed`；当前已纳入测试模块覆盖率为语句 62.96%、分支 47.58%、函数 64.58%、行 65.26%
- 空数据库 Alembic 升级与商品 3D 字段检查：通过
- 当前 MySQL 升级到 `b7d9e1f3a5c8 (head)`：通过
- TypeScript 与 Vite 生产构建：通过
- 浏览器实测：GLB 沙发、茶几、柜体等在方案 3D 场景成功渲染；后台模型字段完整显示；控制台无 error / warning

### 下一施工批次

1. 为 Scene Agent 增加结构化摆放、移动、旋转、删除、碰撞和动线检查工具。
2. 把后台写接口纳入员工身份与角色权限；当前登录后置阶段不应直接公网开放 `/admin` 和商品写接口。
3. 增加模型压缩质量门禁、缩略图生成和 Blender Worker 作业协议。

## 2026-07-31 Web 3D 客户编辑器第二批

- 将方案详情页原只读体块预览升级为可操作的 Web 3D 空间编辑器：
  - 点击家具选中并显示商品名、SKU、位置和角度。
  - 支持 X/Z 平面拖动、绕 Y 轴旋转、10cm 方向微调和 15° 快速旋转。
  - 支持撤销、重做及 `Ctrl/Cmd+Z`、`Ctrl/Cmd+Y`、方向键、`R` 键盘操作。
  - 家具完整占地会被限制在当前房间包围盒内，服务端仍会复核不规则户型。
- 新增确定性“AI 方案 → SceneDocument 1.0”转换：
  - 房间、相机、家具尺寸、SKU 与初始摆位直接生成统一米制场景。
  - Mock 家具明确使用 `DEMO-` SKU，仅作本地演示，不伪装为云端保存成功。
- 新增场景编辑历史内核，最多保留 50 次修改；撤销后产生新修改会正确清空重做分支。
- 正式方案通过 `planVersionId` 自动恢复或创建服务端场景：
  - React StrictMode 并发加载共享同一个请求。
  - 连续修改经过 800ms 防抖并串行保存，不会因并发写入制造假版本冲突。
  - 云端恢复、等待保存、保存中、已保存、离线和版本冲突均有明确状态。
- Three.js、React Three Fiber 与编辑器代码改为进入“3D 布局”标签时按需加载：
  - 首屏主 JS 从约 1.32MB 降至约 495KB。
  - 3D 独立包约 876KB，只在客户打开编辑器时下载。
- 响应式验收修复 Canvas 默认 150px 高度问题；390px/375px 移动端工具栏分层显示，无横向溢出。

### 验证

- 前端全量测试：`21 passed`
- 本批场景内核覆盖率：语句 98.18%、分支 87.5%、函数 100%、行 100%
- TypeScript 与 Vite 生产构建：通过
- 浏览器实测：WebGL 挂载、懒加载、家具选择、10cm 微调、撤销/重做和移动端布局通过
- 浏览器控制台：无 error / warning
- 生产依赖审计仍报告 React Router 6 的 2 项 moderate；当前链接与导航目标均为应用内部常量，SSR 漏洞路径不适用。官方修复线需要升级 React Router 7，未使用 `--force` 破坏性升级，留待单独迁移验证。

### 后续承接

商品 GLB 资产链路已在第三批完成，后续进入 Scene Agent 空间操作工具与 Blender Worker。

## 2026-07-31 Web 3D 场景底座第一批

- 确定客户产品链路：Web 3D 编辑器负责实时交互，Scene Agent 只修改结构化场景，商品模型库提供真实 SKU/GLB，Blender Worker 后续负责高质量渲染。
- 新增统一 `SceneDocument 1.0` 契约：
  - 单位固定为米，采用右手坐标系、Y 轴向上。
  - 支持房间多边形、层高、墙厚、门窗洞口、SKU 家具实例、变换、材质覆盖和相机。
  - 拒绝零面积户型、重复实例编号、无效墙体引用、异常缩放和额外未知字段。
- 新增 `design_scenes` 与 `design_scene_versions`：
  - 一套不可变方案版本对应一个当前 3D 场景。
  - 每次保存产生不可变历史快照，不覆盖旧版本。
  - 客户更新必须携带 `base_version`，过期写入返回 409，防止多个页面静默覆盖。
- 新增匿名会话隔离的场景 API：
  - `POST /api/design/plan-versions/{plan_version_id}/scene`
  - `GET/PUT /api/design/scenes/{scene_id}`
  - `GET /api/design/scenes/{scene_id}/versions`
  - `POST /api/design/scenes/{scene_id}/validate`
- 场景语义校验已接商品库：家具必须引用有效 SKU；门窗不得超出墙长或层高；家具中心点在房间外会产生警告。
- 方案结果新增 `planVersionId`，前端可以把所选 AI 方案准确绑定到服务端 3D 场景。
- 前端新增同构场景 TypeScript 类型及创建、读取、更新、历史和重新校验 API，为下一批编辑器状态管理和 Scene Agent 工具调用提供稳定边界。

### 验证

- 后端全量测试：`48 passed`
- 前端全量测试：`11 passed`
- 空数据库迁移到 `a2b4c6d8e0f1 (head)`：通过，且迁移链只有一个 head
- Python 编译检查：通过
- TypeScript 与 Vite 生产构建：通过

### 下一施工批次

1. 将现有 `RoomView3D` 升级为按需加载的正式编辑器，支持选择、移动、旋转、吸附、撤销/重做与自动保存。
2. 给商品库补充 GLB 地址、真实三维尺寸、模型状态和许可来源，并接入首批可商用模型。
3. 把规则布局升级为 Scene Agent 工具调用：摆放、移动、删除、碰撞检查与动线检查全部输出结构化操作。
4. 设计隔离的 Blender Worker 作业协议，禁止客户输入直接成为 Blender Python 代码。

## 2026-07-31 风格案例图片轮播

- 将 `case_image/` 中 8 种风格、每种 3 张原始 PNG 接入风格案例数据。
- 新增通用风格轮播组件，支持自动播放、上一张/下一张、圆点定位、悬停与键盘聚焦暂停，并尊重“减少动态效果”系统设置。
- 风格案例库卡片、首页风格预览、风格详情弹窗统一使用真实案例图片。
- 修正收藏按钮嵌套交互元素的问题，增加轮播、收藏、详情弹窗的无障碍名称和状态。
- 生成 1280px、WebP 质量 82 的网页资源副本：24 张图片由约 47MB 降至约 1.7MB，原始 PNG 保留不变。
- 验证：轮播单元测试 4 项通过；TypeScript 与 Vite 生产构建通过；桌面端和 390px 移动端 Playwright 页面验证通过，无横向溢出。

### 后续建议

- 案例图进入正式运营后，可迁移至对象存储/CDN，并由后台维护风格、排序、封面和上下架状态。
- 当前前端主包仍有约 1.3MB，后续可通过路由懒加载拆分 3D 与非首屏页面代码。

## 2026-07-29 V2 项目接管与方向确认

- 当前第一产品目标调整为：**客户无需登录即可自行完成房屋定制的智能化应用**
- 服务端前期负责提供商品、材料、报价规则、模型和生成能力；员工销售端与用户登录后置
- 允许使用 `.env` 中已配置的 AI 模型，并以高质量模拟商品、材料、案例和图片先完成可用闭环
- GitHub 仓库：`zhouyulin123/HausProject`，接管时为空仓库
- 新增 `AI家装项目V2开发路线.md`，明确工程底座、客户自助闭环、LangGraph Agent、空间图像、提案后台和后续商业能力六个阶段
- 当前施工顺序：Git 安全基线 → 工程加固 → 匿名会话与方案版本 → LangGraph Agent V1

### 当前约束

- `.env`、用户上传、模型缓存和构建产物不得进入 Git
- 商品 SKU、材料单价和报价计算必须由数据库与确定性程序提供，AI 不得编造
- 模板或 Mock 降级必须明确标识，不得作为真实 AI 成功结果展示
- 数据库暂无真实业务数据，但结构变化仍通过迁移管理，避免形成不可维护的手工表结构

### 下一步

1. 初始化 Git 并连接 GitHub 空仓库
2. 补齐依赖、迁移、测试与运行说明
3. 修复任务失败状态、上传校验和前端静默降级
4. 设计并实现匿名客户会话与方案持久化

### 第一批工程加固结果

- 已初始化 Git，`main` 已同步至 `zhouyulin123/HausProject`
- 已配置仓库级 GitHub noreply 提交身份，不修改本机全局 Git 设置
- 已验证 `.env`、上传文件、Excel 临时文件、模型缓存、依赖和构建产物不会进入 Git
- 新增 pytest 测试底座和开发依赖文件
- 图片上传新增大小、MIME、文件签名和扩展名校验，使用检测到的可信格式保存
- 方案生成发生非预期异常时会回滚并持久化 `failed`、错误原因和归零进度
- 移除设计结果中的假 PDF 地址，真实 PDF 只由提案接口生成
- 补齐 `reportlab`、`openpyxl` 运行依赖及 `.env.example` 的模型和上传配置

### 验证

- `python -m pytest tests/integration/test_task_generation_failure.py tests/unit/test_upload_validation.py`：7 passed
- `python -m compileall -q app`：通过
- `python list_routes.py`：全部 API 路由正常注册
- GitHub `main` 已核对到提交 `0be6582`

### 第二批：匿名客户会话与刷新恢复

- 新增 `anonymous_sessions`：无需登录的客户会话，默认有效期 30 天
- 新增 `anonymous_session_images`、`anonymous_session_tasks`：明确图片和设计任务的会话所有权
- 新增 API：
  - `POST /api/sessions`
  - `GET /api/sessions/{session_id}`
  - `GET /api/sessions/{session_id}/tasks`
- 创建任务时验证上传图片归属，禁止另一个匿名会话复用图片
- 图片上传支持 `X-Session-ID` 并自动建立所有权关系
- 前端使用 localStorage 保存匿名会话、当前任务和上传图片编号
- 当前生成方案也会本地持久化，刷新结果页或详情页后不再直接丢失
- 新增 Vitest 前端测试入口
- 已在当前 MySQL 安全创建 3 张新增表，未删除或修改旧表数据

### 第二批验证

- 后端：`12 passed`
- 前端：`4 passed`
- 前端生产构建：通过
- MySQL 新增会话表存在性检查：通过
- 剩余风险：任务查询和生成接口还需强制校验 `X-Session-ID`；尚未引入 Alembic
- Vitest 已从 2 升级到 4.1.10，清除测试工具的 critical 告警；当前剩余 4 项（3 moderate、1 high），来自旧 Vite/esbuild 和 React Router，需通过受控主版本升级处理，不能直接执行破坏性 `npm audit fix --force`

### 第三批：匿名会话隔离与数据库迁移

- 所有设计任务读取、需求确认、方案生成和结果查询强制要求 `X-Session-ID`
- 聊天、效果图和提案 PDF 在携带 `task_id` 时强制验证任务归属
- 对“不存在的任务”和“其他会话的任务”统一返回 404，避免通过连续编号枚举客户数据
- 权限校验发生在 DeepSeek、SD 和 PDF 服务调用之前，越权请求不会消耗模型额度
- smoke test 已升级为：创建匿名会话 → 带会话上传 → 创建任务 → 生成与导出
- 新增客户主路由注册测试，避免路由模块语法错误漏过服务测试
- 引入 Alembic 1.18：
  - 全新数据库可直接 `python -m alembic upgrade head`
  - 当前 MySQL 已安全接管到 `3e9d6b1a7c42 (head)`
  - 统一 `design_tasks.customer_id` 索引并补齐客户外键
  - 应用启动不再隐式 `create_all`，一键启动会先迁移再启动

### 第三批验证

- 后端：`24 passed`
- 前端：`4 passed`
- 前端生产构建：通过
- 空 SQLite 从零迁移到 head：通过
- 当前 MySQL `alembic current`：`3e9d6b1a7c42 (head)`
- `alembic check`：`No new upgrade operations detected`

### 第四批：方案版本、报价快照与可信提案

- 新增 `design_revisions`、`design_plan_versions`、`quote_snapshots`：
  - 每次方案生成形成递增版本，保存当时的确认需求、图片分析上下文、生成器和完整方案
  - 每个方案保存独立报价快照，历史版本不随商品或报价规则变化而漂移
  - 数据库外键和唯一约束保证任务版本、方案编号与报价一一对应
- 方案生成在同一事务内同时写入旧结果兼容记录和新版快照，失败时整体回滚
- 新增客户会话内的版本查询：
  - `GET /api/design/tasks/{task_id}/versions`
  - `GET /api/design/tasks/{task_id}/versions/{version}`
- 原结果接口优先读取最新正式版本；旧任务没有版本快照时仍兼容旧结果
- 结果页刷新后优先从服务端恢复当前任务，不再依赖浏览器缓存中的完整方案
- 提案 PDF 改为只接收 `task_id + plan_id`：
  - 方案名称、家具明细和报价从服务端最新快照读取
  - 客户端提交的伪造方案内容不会进入 PDF
  - 导出文件名使用数据库方案版本 ID，不使用外部方案字符串拼接路径
- 当前 MySQL 已升级至 `6c4679cf9722 (head)`

### 第四批验证

- 后端：`29 passed`
- 前端：`5 passed`
- 前端 TypeScript 检查与生产构建：通过
- 空 SQLite 从零迁移到最新 head：通过
- 当前 MySQL `alembic current`：`6c4679cf9722 (head)`
- `alembic check`：`No new upgrade operations detected`

### 接下来

1. 为方案版本增加前端历史版本查看与“基于此版本继续优化”
2. 增加预算上限条件分支和确定性调整策略
3. 处理前端大包拆分和受控依赖升级（当前构建主包约 1.32 MB）

### 第五批：LangGraph Agent V1 首条生产工作流

- 移除原有只返回 `{"status": "mocked"}` 的单节点占位 Graph
- 引入 LangGraph 1.x 正式依赖，并建立类型化 `DesignAgentState`
- 生产方案生成接口已切换至四节点工作流：
  1. `prepare_context`：合并确认需求与真实图片分析上下文
  2. `generate_plans`：调用 DeepSeek；仅在明确不可用时进入模板降级，并记录原因
  3. `calculate_quote`：调用商品库校验与确定性报价，AI 不能决定 SKU 单价
  4. `validate_quality`：校验有效商品、报价结构和合计一致性，未通过时整次任务失败
- 所有节点记录状态、来源与耗时；模板降级额外记录 `fallback_reason`
- 工作流轨迹随方案版本写入 `workflow_trace_snapshot`，可通过版本详情接口查询
- 工作流使用依赖注入连接现有模型、模板和报价服务，测试不调用付费模型
- 当前 MySQL 已升级至 `c19eadef8b8b (head)`

### 第五批验证

- LangGraph 工作流单测覆盖真实生成、模板降级、报价门禁：`3 passed`
- 工作流、版本快照和生产生成接口组合测试：`9 passed`
- 后端完整回归：`33 passed`
- Python 编译检查：通过
- 空 SQLite 从零迁移到最新 head：通过
- 当前 MySQL `alembic current`：`c19eadef8b8b (head)`
- `alembic check`：`No new upgrade operations detected`

### LangGraph 下一步

1. 增加预算上限条件分支：超限时自动调整商品组合或明确提示
2. 增加“基于历史版本继续优化”的工作流入口

### 第六批：付费模型验收与持久化后台生成

- 使用当前 `.env` 配置执行一次真实 DeepSeek 付费冒烟：
  - 输入 96㎡三室两厅、儿童家庭、原木/现代简约需求和两条图片空间观察
  - 真实生成 3 套方案，每套 4 个经商品库校验的 SKU
  - 三套确定性商品报价分别为 ¥33,840、¥31,879、¥47,180
  - `generate_plans` 耗时约 24.95 秒，确定性报价耗时约 16ms
  - `generator=llm`，未进入模板降级
- 新增 `generation_runs` 和 `generation_run_events`：
  - 保存 attempt、queued/running/completed/failed、真实进度、当前节点与错误
  - 每个 LangGraph 节点完成后立即写入来源、耗时和详细信息
  - 活动任务自动复用，避免刷新或重复点击造成重复付费调用
  - 失败后创建递增 attempt，可查询历史失败依据并重新执行
- 新增后台生成接口：
  - `POST /api/design/tasks/{task_id}/generate-async`
  - `GET /api/design/tasks/{task_id}/generation`
- 后台执行器使用独立数据库会话，不复用请求结束后的 SQLAlchemy Session
- 前端生成流程改为入队、轮询持久化状态、完成后读取正式方案
- 保留原同步生成接口兼容已有内部调用
- 当前 MySQL 已升级至 `75fbc557e2ce (head)`

### 第六批验证

- 后端完整回归：`38 passed`
- 前端完整回归：`6 passed`
- 前端 TypeScript 检查与生产构建：通过
- 空 SQLite 从零迁移到最新 head：通过
- 当前 MySQL `alembic current`：`75fbc557e2ce (head)`
- `alembic check`：`No new upgrade operations detected`

### 后台任务边界

- 当前使用 FastAPI `BackgroundTasks`，适合现阶段单机、小范围客户试用和 I/O 型模型请求
- 数据状态已经持久化，但进程在模型调用中途退出时不会自动接管未完成任务
- 多进程或正式公网规模前需切换到 Redis + 独立 worker；现有 run/event 表可以直接作为任务状态层复用

### Windows 一键启动器修复

- 修复 `启动豪斯.bat` 使用 LF 换行时被 `cmd.exe` 拆坏命令的问题
- 新增 `.gitattributes`，强制所有 `.bat` 文件保持 Windows CRLF 换行
- 启动目录改为安全引用 `"%~dp0"`，兼容项目路径包含空格
- 新增 `启动豪斯.bat --check`，可在不启动服务窗口的情况下检查 Python、npm 和数据库迁移环境
- 当前机器启动器自检通过，数据库版本为 `75fbc557e2ce (head)`

## 2026-07-24 一键启动脚本 + 3D 布局（最小验证）

- 施工：Claude Code
- 当前状态：3D 布局 MVP 跑通（Three.js 参数化，规则式摆位）；Agent 化下一步做

### 已完成

- **一键启动脚本** `启动豪斯.bat`（项目根）：检测/装前端依赖 → 起后端 8081 + 前端 8080 → 5s 后自动开浏览器
- **3D 布局 MVP**（Three.js / react-three-fiber）：
  - 依赖：three@0.160 + @react-three/fiber@8 + @react-three/drei@9
  - `src/lib/roomLayout.ts`——规则式布局引擎：解析家具尺寸文本，按类别摆位（沙发靠后墙、茶几在前、柜子靠前墙、床靠侧墙、灯具落角、其余沿墙排布），输出场景坐标（米）
  - `src/components/design/RoomView3D.tsx`——渲染房间盒子（地面+两面墙+网格）+ 家具体块（悬停显示名称）+ OrbitControls（拖动旋转/滚轮缩放）
  - 方案详情页新增「3D 布局」Tab，聚焦用户主选空间
- **踩坑修复**：
  - r3f Canvas 在 framer-motion tab 动画中挂载时初次测量失败（卡 300×150）→ 挂载后触发一次 resize 兜底
  - 详情页 tab 的 AnimatePresence 已在早前移除，3D tab 才能正常挂载
  - Canvas 设 `frameloop="demand"` + `preserveDrawingBuffer`（降 CPU / 便于截图）

### 验证

- 布局引擎单测（Node 复刻逻辑跑真实家具数据）：客厅沙发 z=-1.8 靠后墙、茶几 z=-0.55 在沙发前、卧室床靠侧墙旋转 90°，坐标全部合理
- 浏览器：canvas 正确渲染 1654×688（WebGL 活跃）、信息条「客厅 · 4.6m×5.6m · N 件家具」正确、零控制台/服务端报错
- 注：WebGL 画布在当前工具环境下截图不稳定，未取到清晰像素图；需在浏览器实际查看（localhost:8080 → 任一方案详情 → 3D 布局）

### 下一步

1. **Agent 化**（用户已要求）：LangGraph / 工具调用，让 AI 能查商品库、算面积用料、按报价规则实算
2. 3D 可选增强：真实家具模型替换体块、拖动家具改布局、导出 3D 截图进提案

## 2026-07-23 (深夜) 店铺信息可配置：提案 PDF 品牌化

- 施工：Claude Code
- 当前状态：店名/电话/微信/地址/标语/logo 可在 /admin 网页配置，即时生效到提案 PDF

### 已完成

- **shop_settings 表**（单行 id=1）+ `shop_service`（首次访问用 .env 默认值播种，之后以库为准）
- **接口**：`GET/PUT /api/shop`、`POST /api/shop/logo`
- **PDF 品牌化**（`pdf_service.build_proposal_pdf` 接收 shop dict）：
  - 页头：有 logo 时展示 logo + 店名（Table 布局），否则纯店名
  - 页脚：标语 · 电话 · 微信 · 地址（按有值项拼接）
  - proposal 路由从 DB 读店铺信息并解析 logo 本地路径传入
- **前端**：`/admin` 新增「店铺设置」Tab（`ShopSettingsPanel`）——店名/标语/电话/微信/地址表单 + logo 上传预览，保存后提示「下次导出即生效」
- **config**：新增 `shop_name/shop_phone/shop_wechat/shop_address/shop_slogan` 默认值

### 验证

- API：默认播种「AI 家装定制助手」→ 改为「木言家居 · 全屋定制」+ 电话/微信/地址/标语 → 生成 PDF
- PDF 实测：页头显示「木言家居 · 全屋定制」，页脚完整拼出标语+电话+微信+地址
- 浏览器：设置页正确回显、网页改标语→保存→后端持久化确认；测试数据已重置为中性默认值
- 控制台零报错

### 后续可选

1. 前端站内页头/页脚也读 shop_name（目前仍是「AI 家装定制助手」占位；需 app 级加载店铺信息）
2. 客户详情页（点开看某客户全部方案与提案）
3. 权限/角色区分（客户端 vs 内部工具页）
4. 3D 布局（Three.js 参数化路线）

## 2026-07-23 (晚) 第三期（下）：商品库管理页 /admin

- 施工：Claude Code
- 当前状态：可在网页上直接维护商品库（不再只能靠 Excel），第三期完成

### 已完成

- **后端商品库写接口补齐**（`app/api/routes/products.py`）：
  - `PATCH /products/{id}`（编辑）、`POST /products/upload-image`（产品图上传，存 uploads/products/）
  - 定制规则 CRUD：`POST/PATCH/DELETE /products/quote-rules[/{id}]`
- **管理页 `/admin`**（导航「商品库」）：
  - 成品家具 Tab：搜索、卡片列表（缩略图/SKU/类别空间风格/价格）、新增/编辑弹窗（`ProductFormModal`，含图片上传预览）、内联确认下架（软删除）
  - 定制报价 Tab：表格展示 + 顶部快速新增行（项目/档位/单价/单位）+ 删除
  - 数据实时回读，改完立即反映到 AI 方案与报价单

### 验证

- 后端：新增→编辑（改价+卖点）→定制规则增删→软删除后不再出现在列表，全部正确
- 浏览器：/admin 加载 20 件真实产品与 SKU；UI 新增产品走通（20→21，列表即时出现）；定制报价表格正常；测试数据已清理回 20 件；控制台零报错

### 第三期完整回顾（本阶段三次提交）

1. AI 接通自家货：方案家具/报价全部来自商品库，后端回填真实价格
2. 品牌提案 PDF + 客户跟单
3. 商品库管理页 /admin

→ 现在从「录入产品 → AI 用自家货出方案+效果图 → 生成品牌报价 PDF → 客户建档跟单」全链路打通，是一套可用于自家生意的内部工具。

### 后续可选

1. 提案品牌信息可配置（店名/电话/logo，目前在 pdf_service.py 常量）
2. 客户详情页（点开看某客户全部方案与提案）
3. 权限/角色区分（客户端 vs 内部工具页）
4. 3D 布局（之前评估：Three.js 参数化路线，中等难度）

## 2026-07-23 (傍晚) 第三期（上）：品牌提案 PDF + 客户跟单

- 施工：Claude Code
- 当前状态：销售可一键生成带报价单的品牌提案 PDF 发客户；店内客户跟单页上线

### 已完成

- **品牌提案 PDF**（`app/services/pdf_service.py`，reportlab + 微软雅黑）：
  - 内容：品牌头 → 方案名/风格/推荐指数/预算 → 效果图（若该方案渲染过）→ 方案综述 → 布局建议 → **本店产品报价单**（成品+定制明细表，斑马纹，合计高亮）→ 温馨提示 → 页脚联系方式
  - 接口 `POST /api/design/proposal-pdf`（body: plan + task_id），PDF 存 `uploads/`，返回可微信转发的 URL
  - 品牌名/联系方式在 `pdf_service.py` 顶部常量（`SHOP_NAME`），待用户替换为自家品牌
  - 前端详情页「导出提案 PDF」按钮：生成中/已导出/失败三态，成功后自动打开 PDF 并把「我的方案」状态记为已导出
- **客户跟单**（店内轻 CRM）：
  - `customers` 表 + `design_tasks.customer_id` 列（手动 ALTER 迁移）
  - API：增/查/搜/改 + `attach-task`（把方案任务挂到客户名下）
  - 前端 `/customers` 页（导航「客户跟单」）：新增客户表单、姓名/电话搜索、方案数标签、「关联当前方案」按钮（当前会话生成过方案时出现）
- **修复**：PDF 大标题与 meta 行重叠（ParagraphStyle 缺 leading）

### 验证

- API：建客户→搜索→关联任务 13→详情显示 1 个方案；PDF 生成成功且报价单 7 行合计 ¥20,410 验算正确
- PDF 视觉：排版干净、中文正常、表格斑马纹与合计高亮符合品牌色
- 浏览器：客户页新增「李先生」成功、列表与方案数标签正确；详情页导出按钮走通（已导出状态 + 自动打开）

### 剩余（第三期下 + 后续）

1. 管理页 /admin：录入/编辑产品、上传产品图（当前靠 Excel 导入）
2. 提案 PDF 品牌信息可配置化（店名/电话/logo 进 .env 或设置页）
3. 客户详情页（点开看该客户全部方案与提案记录）
4. 效果图放进提案的覆盖率：生成方案后引导先渲染效果图再导出

## 2026-07-23 (下午) 商品库二期：AI 接通自家货

- 施工：Claude Code
- 当前状态：AI 方案的家具与报价全部来自自家商品库——「AI 只卖自家的货、只报自家的价」

### 已完成

- **桥接层**（`app/services/catalog_service.py`）：
  - `build_catalog_context`——商品库 + 定制价目表压缩成 LLM 上下文，随方案生成注入
  - `verify_and_enrich_plans`——LLM 返回后校验 SKU 有效性、**用数据库回填真实价格/材质/尺寸/图片**（AI 无法编造价格）、按价目表实算定制项小计、生成 shopQuote 汇总；无效 SKU 按风格从库中回退挑选；模板降级方案也走同一校验
- **Prompt 升级**：家具改为输出 `{sku, quantity, reason, alternative}`（必须来自商品库）；新增 `customItems`（从价目表选项目+档位，结合房屋面积估算工程量）
- **前端**：`ShopQuoteCard` 报价单组件（成品按件 + 定制按㎡/延米明细表 + 三行汇总）挂到详情页预算 Tab；家具 Tab 卡片支持 SKU 徽章与真实产品图
- **修复两个 bug**：
  1. EffectImage 内嵌 AnimatePresence 与详情页 tab 的 AnimatePresence 嵌套，exit 互相阻塞导致 tab 内容卡死 → 移除内层
  2. React 18 StrictMode 下 `AnimatePresence mode="wait"` 的 exit 完成回调失灵（内容 opacity 变 0 后不卸载、新内容不挂载）→ 详情页 tab 改为 key 重挂载 + 进入动画，不再依赖 exit 回调

### 验证

- API：三套方案家具 SKU 全部真实且组合各异（宠物家庭自动选中猫抓布沙发 SF-002）；定制项单价与价目表逐一对上（680×6.5=4420 等全部验算正确）
- 浏览器：预算 Tab 渲染完整报价单（4 件成品 + 3 项定制，合计 ¥23,504 验算无误）、家具 Tab SKU 徽章正常、tab 切换恢复流畅

### 下一步（第三期：成交武器）

1. 品牌提案 PDF：效果图 + 方案 + 本店报价单合成一份可发客户的文件
2. 客户跟单：客户记录（姓名/电话/户型图/出过的方案）
3. 简单管理页（/admin）：录入/编辑产品、传产品图

## 2026-07-23 商品库第一期：自家产品数据地基

- 施工：Claude Code
- 项目定位已明确：**为自家家具家装生意做 AI 赋能**（定制+成品混合、内部先用）
- 当前状态：商品库表结构 + 模拟数据 + API + 前端家具页切换到数据库，待用户导入真实产品

### 已完成

- **新表**（`app/db/models.py`）：
  - `products`——成品家具 SKU（名称/类别/空间/风格/材质/价格与区间/尺寸/卖点/替代选择/图片/软删除）
  - `custom_quote_rules`——定制报价规则（项目名/计价单位 ㎡·延米·项/材料档位/单价/说明）
- **种子数据**（`backend/seed_data.py`，`--force` 可重灌）：20 件成品（客厅/卧室/餐厅/书房全覆盖）+ 12 条定制规则（衣柜三档板材、橱柜延米、背景墙、榻榻米等，价格贴近行情）
- **Excel 导入工具**（`backend/import_products.py`）：`--template` 生成 `products_import.xlsx` 双工作表模板；导入按 SKU 去重（存在则更新）。**用户后期用它导入真实产品**
- **API**（`/api/products`）：列表（按空间/类别/风格过滤）、`/meta`（动态筛选项）、`/quote-rules`、创建/软删除（留给后续管理页）
- **前端家具页**：从数据库读取（`fetchFurnitureCatalog`，降级 mock）、筛选器选项随商品库动态生成、加载骨架屏、支持真实产品图（`image_url` 有值时覆盖渐变占位）

### 验证

- API：meta 返回 20 件商品与动态类别；客厅筛选 7 件；报价规则 12 条
- 浏览器：家具页渲染 20 件数据库商品（含 mock 中不存在的 SKU）、卧室筛选 5 件正确、控制台零报错

### 下一步（商品库二期，即「AI 接通自家货」）

1. DeepSeek 出方案时家具清单只从 `products` 表选（按风格/空间筛选后注入 prompt）
2. 报价改为：定制项按 `custom_quote_rules` 实算 + 成品按件累加，LLM 负责解释
3. 简单管理页（/admin）：录入/编辑产品，传产品图
4. 之后进入第三期：品牌提案 PDF + 客户跟单

## 2026-07-09 (夜) 本地效果图生成（SD1.5 + ControlNet）打通

- 施工：Claude Code
- 当前状态：核心卖点「效果图」落地——用户在方案详情页按需生成真实效果图，跑在本机 GPU

### 已完成

- **本地 SD 出图**（`app/services/sd_service.py`，RTX 5060 8G）：
  - 基础模型 Dreamshaper-8（SD1.5）+ ControlNet MLSD，共享组件省显存
  - 懒加载 + GPU 串行锁；实测单张 ~6-10s（模型加载后），峰值显存 ~3.6GB
  - 两条路径：**有上传照片** → MLSD 提结构线 → ControlNet 锁户型换风格；**无照片** → 文生图自由出软装齐全的效果图
  - 未装依赖/无 GPU/关闭时抛 SDUnavailable，接口返回 503
- **按需生成**（用户选择）：新接口 `POST /api/design/render`，方案详情页「生成效果图」按钮触发，不在生成方案时自动跑
- **风格 prompt**：中文风格/空间名 → 英文 prompt 映射（`render.py`），SD 对英文响应更好
- **落地保存**：效果图存 `uploads/`，`rendered_images` 表记录，经 `/uploads` 静态路由 + vite proxy 展示
- **前端**：新增 `EffectImage.tsx` 组件（占位→loading 打字点+轮播文案→图片+「换一张」/「基于你的户型」徽章），替换详情页原占位块

### 环境要点（避坑记录）

- RTX 50 系（Blackwell/sm_120）需 **cu128 版 PyTorch**——用户机器已装好（torch 2.11.0+cu128）
- 新版 huggingface_hub 的 Xet 协议会绕过 Clash 代理导致下载失败 → `HF_HUB_DISABLE_XET=1` 走代理直连官方源；hf-mirror 只代理 GET 不代理元数据 HEAD，用不了
- 模型缓存在 `D:/hf_cache`（config 的 `hf_home`）
- `xformers` 未装（sm_120 无预编译包），用 PyTorch 原生 SDPA

### 验证

- 独立脚本：文生图 → MLSD → ControlNet 重绘，三图证明「锁结构换风格」成立
- 接口直测：ControlNet 路径（真实房间图）生成的效果图保留窗/墙/地板结构，换成奶油暖调
- 浏览器：前端 fetch → 后端出图 → /uploads 代理 → `<img>` 加载 768×512 成功

### 下一步建议

1. 效果图 prompt 精修（引入方案的色板/材质/家具进 prompt，让出图更贴合方案文字）
2. img2img 强度调参（ControlNet 当前偏保守，可加 img2img 让原房间纹理参与）
3. 真实 PDF 导出（把效果图 + 方案 + 报价合成 PDF）
4. 用户体系 + 方案云端存储（打通「我的方案」到后端）

## 2026-07-09 (傍晚) 接入 Qwen3-VL 真实图片分析 + 端口调整

- 施工：Claude Code
- 当前状态：户型图/房间照片走真实视觉模型分析，并反哺方案生成；端口迁移到 8080/8081

### 已完成

- **端口调整**：前端 `localhost:8080`，后端 `localhost:8081`（vite proxy、CORS、launch.json、smoke_test、.env.example 已同步）
- **Qwen3-VL 视觉分析接入**（SiliconFlow，`app/services/llm_service.py::analyze_image`）：
  - 主力模型 `Qwen/Qwen3-VL-32B-Instruct`，配置读取 `.env` 的 `VL_API_KEY / VL_API_KEY_BASE_URL / VL_MODEL1 / VL_MODEL2`
  - 上传接口 `POST /api/upload/image` 传真实图片字节给 VL，返回结构化 JSON：image_kind / space_type / room_count / findings / suggestions
  - VL 识别到的空间信息回写 DB（uploaded_images.analysis_json），并覆盖按文件名的粗猜类型
  - 失败降级到占位结果（source=placeholder），前端再降级到本地 mock（source=mock）
- **图片分析反哺方案生成**：generate 时收集该任务下所有图片的 findings，作为 `image_analysis` 上下文一并喂给 DeepSeek 方案生成
- **前端展示升级**（AnalysisResult.tsx）：新增「Qwen3-VL 视觉分析」徽章、空间类型/房间数标签、独立的「装修建议」区块
- **方案生成健壮性**：新增 `_normalize_plans`——过滤 LLM 偶发的残缺方案、截取前 3 套、统一 id 与字段兜底（解决实测中 LLM 返回 5 套含 2 套残缺的问题）

### 验证

- 直接调 VL endpoint：准确识别测试户型图（客厅卧室相邻、厨卫并排、无独立餐厅、L型布局、缺玄关）
- 浏览器端到端：canvas 画户型图 → 上传 → 3 秒返回真实 VL 分析 → 页面渲染徽章+findings+建议，控制台零报错
- smoke_test.py：11 项全部 PASS

### 下一步建议

1. 效果图生成（第三方 API 或 SD + ControlNet，届时引入任务队列）
2. 真实 PDF 导出（weasyprint / reportlab）
3. 复杂户型可切换 VL_MODEL2（Thinking 版）做多房间动线深度推理
4. 「我的方案」与后端打通（用户体系 + 方案云端存储）


## 2026-07-09 (下午) MySQL 持久化 + DeepSeek LLM + 前后端联调完成

- 施工：Claude Code
- 当前状态：全链路真实化——前端页面 → FastAPI → MySQL 持久化 → DeepSeek 生成，端到端验证通过

### 已完成

- **MySQL 持久化**：本地 MySQL 8（`houseproject_db`），6 张表自动建表（design_tasks / uploaded_images / requirement_parse_results / design_results / chat_logs / users），替换掉全部内存存储
- **DeepSeek LLM 接入**（`app/services/llm_service.py`）：
  - 需求解析：自然语言 → 结构化 JSON（降级：原规则解析）
  - 对话确认：`POST /api/design/chat`，真实设计师人设对话（降级：前端本地规则回复）
  - 方案生成：一次产出 3 套完整方案，结构与前端 `DesignPlan` 对齐（降级：后端模板方案），耗时 24-41s
- **文件上传落地**：真实保存到 `backend/uploads/`，静态路由 `/uploads` 访问，DB 记录含空间识别结果（识别本身仍为占位，待接视觉模型）
- **前后端联调**：前端 `designApi.ts` 改为真实 fetch（vite proxy → 8010），后端不可用时自动降级本地 mock；修复 React StrictMode 双触发导致的重复 LLM 调用（in-flight 去重）
- **端口调整**：后端改用 **8010**（8000 被本机另一项目 Trust Contract AI Agent 占用）
- 重写 `smoke_test.py` 为针对运行中服务的端到端测试，11 项全部 PASS

### 遗留 / 已知问题

- LLM 方案生成偶发输出超长被截断 → 已通过收紧提示词字数缓解，仍有降级模板兜底
- 图片空间识别、效果图生成、PDF 导出仍为占位实现
- 生成接口为同步阻塞（~30s），并发量大时需改异步任务

### 下一步建议

1. 接入视觉模型（如 Qwen-VL）做真实户型图/照片分析
2. 效果图生成（第三方 API 或 SD + ControlNet，届时引入任务队列）
3. 真实 PDF 导出（weasyprint / reportlab）
4. 「我的方案」与后端打通（用户体系 + 方案云端存储）


## 2026-07-09 Web 前端基础版本完成

- 施工：Claude Code
- 需求来源：`AI_home_customization_frontend_prompt.md`（前端开发提示词）
- 当前状态：前端 10 个页面全部完成，构建通过，核心流程已在浏览器中验证

### 已完成

- 技术栈：React 18 + TypeScript + Vite 5 + Tailwind CSS v4 + framer-motion + zustand + react-router v6
- 目录：`frontend/`，启动方式 `cd frontend && npm install && npm run dev`（端口 5173）
- 页面（10 个）：首页、AI 定制表单（4 步向导）、户型图上传、AI 对话确认、方案结果、方案详情（6 个 Tab）、家具推荐（筛选 + 详情弹窗）、风格案例库、我的方案、登录注册
- 视觉体系：米白 / 原木 / 鼠尾草绿 / 陶土橙暖色调，Noto Serif SC 标题字体，自定义 Tailwind 主题 token
- 状态管理：zustand + localStorage 持久化（需求表单、保存的方案、收藏家具）
- Mock 数据：3 套完整设计方案、12 件家具、8 种风格案例、关键词规则 AI 对话回复
- API 层：`src/api/designApi.ts` 统一封装，vite proxy 已代理 `/api` → `localhost:8000`（FastAPI）

### 技术决策

- 未使用 shadcn/ui：自封装轻量组件（Button/Tag/EmptyState 等）以贴合定制视觉体系
- 已验证：TypeScript 零错误、生产构建通过、9 个路由页面移动端（375px）无横向溢出、控制台零报错

### 下一步建议

1. 前后端联调：将 `designApi.ts` 中的 mock 函数替换为真实 fetch 调用
2. 后端内存存储替换为 SQLAlchemy 持久化
3. 接入真实 LLM 需求解析与对话（对应前端 ChatPage）
4. 真实效果图生成与 PDF 导出



## 2026-06-04 初步 MVP 后端闭环

- 项目经理：Codex
- 施工 Worker：Gemini Backend MVP API Worker
- 需求来源：`AI家装项目初步项目计划书.md`
- 当前状态：第一阶段后端 MVP 闭环已初步实现并通过 smoke test

### 已完成

- 启用 FastAPI `/api` 路由。
- 实现图片上传模拟接口：`POST /api/upload/image`。
- 实现设计任务创建接口：`POST /api/design/tasks`。
- 实现结构化需求解析接口：`GET /api/design/tasks/{task_id}/requirement`。
- 实现需求确认接口：`POST /api/design/tasks/{task_id}/confirm-requirement`。
- 实现方案生成模拟接口：`POST /api/design/tasks/{task_id}/generate`。
- 实现任务状态查询接口：`GET /api/design/tasks/{task_id}`。
- 实现结果查询接口：`GET /api/design/tasks/{task_id}/result`。
- 实现导出接口：`POST /api/design/tasks/{task_id}/export-pdf`。
- 使用内存存储承载 MVP 数据流。
- 使用确定性规则模拟中文需求解析、报价计算、报告生成和效果图占位。
- 新增 smoke test 覆盖完整 API 流程。

### 验证结果

- `python list_routes.py`：确认计划书要求的核心 API 路由均已注册。
- `python smoke_test.py`：上传图片、创建任务、解析需求、确认需求、生成方案、查询结果、导出报告全流程通过。

### 当前限制

- 数据使用内存存储，服务重启后会丢失。
- 需求解析是规则模拟，不是真实 LLM。
- 效果图生成是占位 URL，不是真实 AI 绘图。
- PDF 导出当前是文本报告 artifact + mock `pdf_url`，不是正式 PDF 文件。
- 尚未实现前端 Web/H5 页面。
- 尚未接入数据库迁移、对象存储、异步任务队列和后台管理。

### 下一步建议

1. 构建 Web/H5 前端最小流程页面并接入现有 API。
2. 将内存存储替换为 SQLAlchemy 持久化模型。
3. 接入真实 LLM 需求解析，并保留当前规则解析作为 fallback。
4. 接入真实 PDF 生成能力。
5. 接入真实效果图生成服务或明确半自动占位流程。
