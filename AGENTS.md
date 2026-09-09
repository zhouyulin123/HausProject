# AI Agents Configuration (LangGraph Architecture)

This document defines the configuration, roles, and interactions of the various Agents used in the AI Home Decor application. We are using a multi-agent architecture orchestrated by LangGraph.

## 1. Orchestrator Agent (Master Graph)
*   **Role:** The central router and state manager. It receives the initial user input (image + text) and determines the execution flow, passing state between specialized agents.
*   **Framework:** LangGraph `StateGraph`
*   **State Definition:**
    *   `user_input_text`: string
    *   `uploaded_image_urls`: list[string]
    *   `parsed_requirements`: dict (JSON)
    *   `image_analysis_result`: dict
    *   `generated_images`: list[string]
    *   `quote_result`: dict
    *   `current_step`: string

## 2. Requirement Parsing Agent (需求理解 Agent)
*   **Role:** Extracts structured data (JSON) from the user's natural language input.
*   **Model Recommendation:** DeepSeek-Coder / GPT-4o (Strong structured output capabilities required).
*   **Prompt Strategy:** Few-shot prompting + Strict JSON Schema output format.
*   **Input:** `user_input_text`
*   **Output:** `parsed_requirements` (JSON matching `9.2` in the project plan)
*   **Tools/Functions:** None (Relies on LLM structured output capabilities).

## 3. Image Analysis Agent (图像分析 Agent)
*   **Role:** Analyzes the uploaded room photo or floor plan to understand space type, existing layout, and potential constraints.
*   **Model Recommendation:** GPT-4o / Qwen-VL (Vision Language Models).
*   **Prompt Strategy:** Ask specific questions about the image (e.g., "What type of room is this?", "Are there any existing windows or doors?").
*   **Input:** `uploaded_image_urls`
*   **Output:** `image_analysis_result` (Structured tags and descriptions).

## 4. Drawing Dispatch Agent (绘图调度 Agent)
*   **Role:** Takes the parsed requirements and image analysis to formulate the optimal prompt and parameters for the external image generation API (e.g., ControlNet).
*   **Model Recommendation:** A fast, cheap LLM (e.g., GPT-4o-mini or DeepSeek-Chat) to act as a prompt translator.
*   **Input:** `parsed_requirements`, `uploaded_image_urls`
*   **Output:** Generates Prompts and calls external Image Generation API (via Tool/ToolNode in LangGraph).
*   **Tools:**
    *   `generate_interior_design`: An API wrapper calling SD/ControlNet or third-party interior design APIs.

## 5. Quote Calculation Agent (报价生成 Agent)
*   **Role:** Calculates the estimated price range based on the structured requirements and predefined pricing rules.
*   **Implementation:** This might not need a complex LLM; it can be a deterministic Python function (a standard node in LangGraph) that executes the pricing logic based on database rules.
*   **Input:** `parsed_requirements`
*   **Output:** `quote_result` (Price ranges and breakdowns).

## LangGraph Workflow Example

```python
# Conceptual Workflow
from langgraph.graph import StateGraph

workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("parse_requirements", requirement_parsing_agent)
workflow.add_node("analyze_image", image_analysis_agent)
workflow.add_node("calculate_quote", quote_calculation_agent)
# workflow.add_node("generate_image", drawing_dispatch_agent) # Might be asynchronous or separate

# Define Edges
workflow.set_entry_point("parse_requirements")
# Parallel processing if possible
workflow.add_edge("parse_requirements", "calculate_quote")
# ...
```

## 当前开发状态（2026-09-09）

- 方案来源已形成端到端追溯契约：服务端在任务结果、版本详情、个人方案与单方案快照中按不可变 revision 返回 `generationSource`，前端方案卡片和详情页区分 AI 模型、系统模板、Agent 精修、用户编辑与显式 Demo；未知值明确显示“来源未知”，不按供应商名称猜测。
- 统一工作台不再依赖浏览器本地项目索引才能恢复：服务端 Agent checkpoint 返回已确认需求与经 `RoomModel` 校验的最新空间模型，本地缓存丢失时可按任务 ID 重建项目骨架；历史不完整需求逐字段归一化，不推测缺失业务事实。
- 服务端 checkpoint 的受控事实与证据已进入工作台运行态；房间面板只展示空间、尺寸、风格、预算和地区白名单字段，并明确标记置信度或待确认状态。旧浏览器项目缓存通过 v5 迁移补齐事实容器。
- 正式方案详情页已移除按 URL 静默载入 `mockDesigns` 的后门；本地 Demo 只能来自显式 Demo 生成流程写入的运行态，任意 `plan-a/plan-b` 地址不再伪装成真实方案。
- Agent 人工审批已形成显式状态迁移：决定、checkpoint 版本递增和独立审批时间线事件在同一事务提交；原始 Agent turn 响应保持不可变。报价、布局和施工风险的审批不会绕过确定性硬门禁，决定后进入等待新一轮校验或用户修改请求。
- 后端 Python 测试、测试夹具和手工冒烟脚本已统一迁移到仓库根目录 `tests/`，根目录 `pytest.ini` 与 CI 从仓库根执行测试；`backend/` 不再保存测试文件。
- 统一工作台预算栏已停止解析商品展示价格，只展示服务端方案中的确定性 `shopQuote` 报价快照；Agent 对话失败会保留原 `client_turn_id` 并提供同轮重试。端到端冒烟脚本已改用 `generate-async` 与独立 Generation Worker，不再调用已停用的同步生成接口。
- 阶段 1–3 的本地工程闭环已完成：统一用户工作台、受控 Agent 状态机、持久化生成/效果图/Blender Worker、商品与报价门禁、房间级 3D、定制家具草稿、统一执行时间线均已接通。
- 需求解析、空间识别、用户画像、Agent 多次模型调用、方案生成和公开 Demo 的实际模型尝试与成本已进入持久化账本；模板、未知成本与真实计费明确区分。
- 上传、需求解析、生成、旧精修入口和 Demo Agent 已建立稳定幂等契约，重复请求不会重复调用模型；时间线事件保留原始 `request_id`，便于跨 HTTP 与 Worker 追踪。
- 当前全量验证基线：后端 918 项通过；前端 64 个测试文件共 284 项通过；TypeScript、Vite 生产构建、本轮相关文件 Ruff 与差异检查通过。全仓 Ruff 仍有 17 个既有未使用导入或变量问题；构建仅保留 `vendor-three` 约 667 KB 的既有分包告警。
- Alembic 代码与本机 MySQL 均位于唯一 head `7c8d9e0f1a2b`；升级前备份已保存在 `outputs/backups/`，启动预检通过。
- 商品运营侧已具备受厂家角色保护的完整目录、地区就绪度统计、商业来源与价格证据录入、乐观并发控制和失败关闭核验；桌面与移动端运行态已验收。
- 运营质量页已接入真实案例治理就绪度：清单必须为可信 schema 2.0，不得在发布分组混入合成案例，并需至少 20 个去重 `private_real` 案例且 development、regression、blind 三组均非空；接口与页面统一仅管理员可访问，只展示授权、标注、用途与分组聚合阻断，不泄露案例内容或资产路径。
- 运营质量页已展示采用、删除、替换、移动、最终选择、修改率与满意度等匿名反馈回流指标；无样本时显示 `--`，并可导入由评测流程生成的 schema 2.0 已签名失败分诊 JSON，签名真实性仍由服务端失败关闭验签。
- 可信布局评测只准入可由冻结 `SceneDocument` 确定性复算的约束；当前缺少通行路径图和容量模型，因此 `walkway_width` 与 `maximum_occupancy` 在新标注准入阶段明确拒绝，历史记录仍可读取但不能产生可信证据。
- 生产方案追溯只接受受控环境签名的 `production_acceptance` cohort，精确绑定环境、cutover、任务和方案版本；全部成员均进入核验，历史 Demo、坏绑定或第 20 条之后的坏样本不能被随机抽样绕过。
- 敏感模型、Prompt、布局规则、商品数据或发布门禁变更的 PR 必须取得受保护真实案例工作流针对同一提交 SHA 签发的 Ed25519 脱敏 proof；普通 PR runner 不读取 blind 资产或私钥。GitHub 仍需管理员配置公开验签变量、受保护环境密钥和 required check。
- 失败簇管理员状态机最多推进到 `resolved`，不能手填 `verified`；受保护发布门禁可在显式提供待复测目标时，根据 development、regression、blind 三组完整候选/基线证据签发提交与目标集合绑定的 HMAC 复测证明。管理员质量页仅导入该证明，服务端验签并原子推进 `resolved -> verified`；任一目标复发、版本错配或证据不完整都会失败关闭，后续复发还会自动重开并清除旧验证来源。
- 阶段 4 工具链已具备失败关闭能力，但真实业务验收尚未完成：当前 4 个候选案例均待授权、待标注且未分组，三个 split 准入数均为 0；57 件商品中仍没有通过商业核验且满足地区、库存、价格有效期门禁的可用商品。
- 完成阶段 4 仍需外部输入：至少 20 个去重、脱敏、获授权并完成人工标注的真实案例，development/regression/blind 三组划分与执行评审，通过商业核验的商品数据，受保护评测环境、自托管 runner、独立签名密钥，以及候选/基线的真实运行证据。禁止用合成案例、公开参考商品或手写指标替代。
