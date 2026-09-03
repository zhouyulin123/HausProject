# 真实案例评测集

这个目录只保存案例清单、人工标注和评测输入，不复制客户原始资产。资产通过 `manifest.json` 的相对路径引用，运行时必须显式指定允许的资产根目录。

可信证据链只接受清单 schema `2.0`。当案例标记为 `annotation_status=ready` 时，还必须提供数据集目录内的 `annotation_path` 和对应原始文件 `annotation_sha256`，且内容满足 `real_world_case_annotation/1.0`。历史 `1.0` 清单仅保留读取兼容，不能签发 3.0 可信评测证据。

## 案例准入

案例同时满足以下条件后才会进入离线评测：

- `consent_status` 为 `granted` 或明确无需授权的 `not_required`；
- `annotation_status` 为 `ready`，并填写非空 `label_version`；
- `allowed_purposes` 包含 `offline_evaluation`；
- `split` 已分配为 `development`、`regression` 或 `blind`；
- 资产存在且没有越过指定的资产根目录；
- 填写严格结构化的 `task_input`，且正式任务的需求字段和图片分析 `image_context` 与该输入完全一致；
- `blind` 不允许使用 `synthetic` 案例。

仓库现有四张户型图目前全部处于 `pending`。在确认来源、用途授权和人工标注前，它们不会被评测程序使用，也不能作为“真实案例质量达标”的证据。

## 分组规则

- `development`：允许用于定位成组问题和调整规则；
- `regression`：每次模型、Prompt、规则或数据版本变化后运行；
- `blind`：只由验收负责人运行，不向规则开发过程暴露标签；
- `unassigned`：尚未完成治理，不参与任何指标。

同一个物理案例只允许出现在一个分组。公开研究数据使用 `public_reference`，指标必须与 `private_real` 分开查看；构造案例使用 `synthetic`，不得进入盲测集。

加载清单时会流式计算资产 SHA-256。同一内容即使复制成不同文件名、改用不同 `case_id`，也会被识别为重复物理案例并拒绝整个清单，防止开发集或回归集样例泄漏到盲测集。

## 可信证据格式

不能手写逐例 `CaseResult`。先让正式 Generation Worker 实际执行每个已准入案例，
再以 `run-bindings.template.json` 记录单一 `split`、内部案例 ID、任务 ID和运行 ID。绑定 schema `3.0` 可另外成对填写数据集根目录内的 `execution_review_path` 与原始文件 SHA-256；没有本次执行评审时两项都必须为 `null`。历史绑定 schema `2.0` 继续作为无人工评审输入读取。收集器只接受：

- 状态为 `completed`、`failed`、`dead_letter`、`cost_limit_exceeded`、`provider_unavailable` 或 `cancelled`，且 task/run 归属一致的可信终态运行；其中取消运行也作为生成失败进入分母，不能用于剔除差样本；
- `generator=llm`，不接受 template 降级、demo、mock、manual、test 或 synthetic；
- 所有终态都必须在执行前冻结模型、静态 Prompt 契约、完整动态输入、规则制品和完整商品上下文；
- 评测绑定同时冻结与任务原文完全一致且 `parser=llm` 的需求解析、实际需求模型名、上传时原始 `vl` RoomModel、实际视觉模型名及绑定前确认日志；规则解析、占位视觉结果、缺少实际模型名的历史记录、确认后的需求和校准后的 RoomModel 投影都不能冒充模型预测；
- 原始 RoomModel 的 `rooms` 按 `room.id` 规范化，空间标注只能用 `rooms.<room_id>.<field>` 等精确路径查找，不会因为案例只有一个房间而猜测数组元素；
- 成功运行还必须唯一绑定同任务的不可变 `DesignRevision`，并保存由其 `DesignPlanVersion` 与 `QuoteSnapshot` 规范化业务内容计算的 `output_digest`；收集时会重算摘要，不信任 `output_snapshot` 自报；
- 成功运行必须存在四个 Worker 节点，且 `generate_plans` 来自 LLM，报价与质量校验来自确定性节点；失败、取消、死信和人工接管终态不得携带 revision、输出摘要或输出快照；
- 同一证据包内每个已准入案例恰好一个运行，同一 run 不得跨案例复用。

需求事实和空间事实始终以人工标注条数作为分母，包括后续方案生成失败的案例。真实模型没有输出某字段、来源或模型名不可信、路径未知时，该事实计为未命中，而不是从分母删除。低置信确认率只以真实 VL 已预测且低置信或明确要求确认的标注事实为分母，并要求追加式确认记录中的先前值和先前置信度都与原始预测一致。历史评测绑定没有预测快照时失败关闭。

创建 GenerationRun 时，评测队列器必须调用
`evals.trusted_evidence.bind_evaluation_run(db, dataset=..., split="regression", case_id=..., task=...)`，在同一事务中写入运行及持久化案例绑定。`evaluation_run_idempotency_key` 也必须传入 `db`、`task` 和 `split`，其身份同时包含案例、split、模型与静态制品版本；只把幂等键传给现有 `generate-async` 不构成可信绑定，服务会失败关闭。Worker 领取与证据收集都会复核任务需求、按上传顺序冻结的图片分析事实、唯一原始资产摘要和执行前版本；错误图片、额外图片、分析变化、需求变化、可变用户画像、绑定后混版、缺少 `task_input` 或历史图片没有摘要时均拒绝执行或签发。

收集器不会接收 CaseResult。revision 的需求快照是人工确认后的生成输入，不是 AI 解析或视觉预测，因此当前不会用它计算需求准确率、空间事实准确率或低置信确认率；在模型预测快照纳入证据链前，这三项保持 `NO EVIDENCE`。有效 SKU、商品匹配、报价复算、预算和风格从不可变方案及报价快照对照 CaseAnnotation。布局硬约束进入分母，但在确定性几何产物纳入同一输出摘要前不信任模型自报的通过标记，因此记为未命中；任何缺失事实都不能由 `output_snapshot` 补齐。

人工满意度与修改事实只接受 `real_world_execution_review/1.0`。评审文件的案例、标签版本、文件 SHA-256 和 `output_digest` 必须全部与本次运行一致；没有匹配评审时满意度与修改率保持零分母，报告显示 `NO EVIDENCE`，不会把缺失评审计成零分。

证据包 5.0 使用独立 HMAC 密钥签名，绑定一个显式 split 的数据集内容指纹、匿名案例指纹、密钥域内匿名 `execution_ref`、运行终态、模型及三个运行时制品摘要，以及输入、真实预测、不可变输出和结果摘要。旧 3.0 的 `output_snapshot` 摘要不能作为不可变输出证据，旧 4.0 也没有绑定真实模型预测。Prompt 摘要从静态系统 Prompt、输出 Schema 和工具/调用参数契约复算；完整动态模型请求另行计算 `input_digest`，不得截断；规则摘要只绑定执行前可读取的生成与报价源码制品；数据摘要绑定模型实际接收的完整商品与定制价目上下文，不依赖成功后选出的方案。签发 CLI 不接受调用方自报版本。文件不包含案例 ID、数据库 task/run ID、资产路径、Prompt、输入、模型输出、原始预测或人工评审原文，只保留匿名引用及摘要。签名密钥必须只配置在受控 Worker/CI，不应写入仓库、命令行或开发者共享环境。

终态失败会进入 `generation_success_rate` 分母并记为失败，但不会伪造 SKU、报价、布局或满意度等它没有产出的指标。`development`、`regression`、`blind` 必须分别绑定、收集、验签和比较；任何 CLI 省略 `--split`、绑定文件 split 不一致、跨 split 案例混入或所选 split 为空都会失败关闭。

跨用户访问和重试边界不能依靠默认零值证明安全。重试边界由可信收集器根据持久化 GenerationRun 的执行次数、上限、终态和事件派生。跨用户访问只能由独立 CLI 对受控 HTTPS 部署执行真实 owner/foreign 会话检查后签发；调用方或普通评测签名者自填 `cross_user_access_checks`、`severe_cross_user_access` 会被拒绝。没有独立安全制品时保留零分母，报告明确显示证据缺口并失败关闭。

安全目标文件只在受控环境保存，允许包含内部 `task_id` 与会话环境变量名，但不得提交仓库或作为报告附件。会话值仅从环境变量读取。下面的占位值表示文件结构，不是真实凭据：

```json
{
  "schema_version": "1.0",
  "split": "regression",
  "versions": {
    "model": "运行绑定中的实际模型",
    "prompt": "sha256:<运行绑定摘要>",
    "rules": "sha256:<运行绑定摘要>",
    "data": "sha256:<运行绑定摘要>"
  },
  "targets": [
    {
      "case_id": "<已准入案例 ID>",
      "task_id": 12345,
      "foreign_control_task_id": 67890,
      "owner_session_env": "EVAL_CASE_01_OWNER_SESSION",
      "foreign_session_env": "EVAL_CASE_01_FOREIGN_SESSION"
    }
  ]
}
```

发布流水线必须把当前应用制品 SHA-256 以 `APP_BUILD_DIGEST=sha256:<64 hex>` 注入受控部署。应用会把合法值返回为 `X-App-Build-Digest`；独立 CLI 会在健康检查、会话有效性检查和每次资源访问中复核该响应头。安全 key 与普通评测 key 必须使用不同 `key_id` 和密钥材料：

```powershell
$env:PYTHONPATH = "backend"
$env:APP_BUILD_DIGEST = "sha256:<当前发布制品的64位十六进制摘要>"
$env:SECURITY_EVIDENCE_KEY_ID = "security-ci-2026-09"
$env:SECURITY_EVIDENCE_HMAC_KEY = "从独立密钥域注入的至少32字节随机密钥"
$env:EVAL_CASE_01_OWNER_SESSION = "<受控 owner 会话 UUID>"
$env:EVAL_CASE_01_FOREIGN_SESSION = "<不同用户或会话 UUID>"
python -m evals.collect_security_access_evidence `
  --manifest backend/evals/cases/real_world/manifest.json `
  --split regression `
  --asset-root . `
  --targets <受控目录>/security-targets.json `
  --base-url https://<受控部署域名> `
  --app-build-digest $env:APP_BUILD_DIGEST `
  --output <受控目录>/cross-user-security.evidence.json
```

CLI 对每个准入案例先要求 foreign 会话读取自己的 `foreign_control_task_id` 返回 `200`，证明该会话真实有效且鉴权链可用；会话只进入请求头，不进入 URL。随后访问 `GET /api/design/tasks/{task_id}/generation`：owner 必须返回 `200`；foreign 返回 `404` 表示通过，返回 `2xx` 形成严重越权事实，其他状态因结果不确定而拒绝签发。公开安全制品不保存 session、token、case ID 或 task/run 原始 ID，仅保存匿名案例指纹、密钥域内 HMAC 运行引用、HTTP 状态与派生计数，并具有最长一小时的有效期。

在仓库根目录运行：

```powershell
$env:PYTHONPATH = "backend"
$env:EVAL_EVIDENCE_KEY_ID = "quality-ci-2026-09"
$env:EVAL_EVIDENCE_HMAC_KEY = "从密钥管理服务注入的至少32字节随机密钥"
$env:SECURITY_EVIDENCE_KEY_ID = "security-ci-2026-09"
$env:SECURITY_EVIDENCE_HMAC_KEY = "从独立密钥域注入的至少32字节随机密钥"
$env:APP_BUILD_DIGEST = "sha256:<当前发布制品的64位十六进制摘要>"
python -m evals.collect_real_world_evidence `
  --manifest backend/evals/cases/real_world/manifest.json `
  --split regression `
  --asset-root . `
  --run-bindings backend/evals/cases/real_world/run-bindings.json `
  --security-evidence <受控目录>/cross-user-security.evidence.json `
  --output backend/evals/reports/evidence/real_world_eval.evidence.json

python -m evals.run_real_world_eval `
  --manifest backend/evals/cases/real_world/manifest.json `
  --split regression `
  --asset-root . `
  --results backend/evals/reports/evidence/real_world_eval.evidence.json `
  --establish-baseline `
  --output-dir backend/evals/reports/real_world
```

`--establish-baseline` 只用于人工批准的首次可信基线。只要清单中存在准入案例，后续运行若未提供 `--baseline-results`，会以输入错误退出；因此模型、Prompt、规则或商品数据制品变更不能静默跳过版本比较。无准入案例时不会签发可信证据。

模型、Prompt、规则或商品数据制品发生变化时，必须额外传入同一评测数据集、同一案例集合生成的签名基线证据：

```powershell
python -m evals.run_real_world_eval `
  --manifest backend/evals/cases/real_world/manifest.json `
  --split regression `
  --asset-root . `
  --results backend/evals/reports/evidence/real_world_eval.evidence.json `
  --baseline-results backend/evals/reports/evidence/baseline.evidence.json `
  --output-dir backend/evals/reports/candidate
```

基线和候选的 split、评测数据集指纹或匿名案例指纹集合不一致时拒绝比较。即使候选仍达到绝对门禁，只要比例指标下降、跨用户访问或无限重试计数增加，版本回归也会失败。盲测证据不能隐式作为 development 或 regression 的候选或基线。

报告和签名证据会绑定准入案例的资产 SHA-256、标签版本、来源和分组。基线与候选即使沿用相同数据版本，只要实际资产、标签或分组发生变化，也会拒绝伪装成同一案例集比较。

评测退出码：`0` 表示全部门禁通过，`1` 表示可信证据完整但质量未达标，`2` 表示清单、证据、签名或密钥不合法。证据收集器成功返回 `0`，任何运行来源、覆盖或签名配置问题返回 `2`。当前清单没有准入案例，因此尚不能签发真实验收证据，也不能在 CI 中当作成功。

公开 trusted evidence `5.0` 的 execution 不包含数据库 `task_id` 或
`system_run_id`。收集器使用证据部署密钥和固定用途域生成
`exec-hmac-sha256:<digest>`；同一部署密钥下引用稳定，切换密钥域后引用变化。
带原始任务、运行主键的 `run-bindings.json` 仅是受控收集器内部输入，禁止作为
公开证据、报告或工单附件外发。读取器严格拒绝带原始主键、非法或重复
`execution_ref` 的公开证据。

## 人工标注最小内容

每例至少保存：脱敏需求、人工确认的 RoomModel、低置信事实、允许商品范围、预算范围、确定性报价结果、布局硬约束、失败标签、标注人与标签版本。用户满意度和人工修改率单独记录，不与确定性事实指标混算。

## 失败样本分诊

失败分诊 `2.0` 不接受独立 failure 文件、人工填写 code 或自由文本分类。CLI
必须读取同一份已验签 trusted evidence `5.0`，并只根据可信运行终态和
`CaseResult` 的结构化分子、分母确定性派生失败类型、严重度、code、tag 与
metric。证据签名无效、split 不一致、案例覆盖不完整或旧公开结构都会失败关闭。

先分别配置 case_id 脱敏密钥和报告签名密钥，再运行 CLI。两把密钥用途不同，不能复用；命令输出中的 `sync_payload` 可直接作为管理员同步接口的 JSON 请求体：

```powershell
$env:EVAL_CASE_ID_SALT = "由评测管理员配置的至少16字符密钥"
$env:EVAL_REPORT_SIGNING_KEY = "由评测管理员配置的至少32字节独立签名密钥"
$env:PYTHONPATH = "backend"
python -m evals.run_failure_triage `
  --manifest backend/evals/cases/real_world/manifest.json `
  --split regression `
  --asset-root . `
  --evidence backend/evals/reports/evidence/real_world_eval.evidence.json `
  --salt-id eval-case-key-v1 `
  --report-id weekly-2026-W36 `
  --candidate-version candidate-2026-W36 `
  --signing-key-id eval-report-key-v1 `
  --output-dir backend/evals/reports/failure_triage
```

报告按失败类型、严重度、数据切分、code、tag 和 metric 聚合，并输出稳定的
HMAC case 别名。报告及其签名同步载荷同时绑定 dataset version、manifest
digest、完整 evidence digest 和涉及的 immutable output digest；聚类还保留
匿名 `execution_ref`，不能脱离原始可信证据重新填写。报告不保存原始 case_id，
也不保存脱敏密钥；同一数据版本需要保持相同密钥和 `salt-id`，才能跨次比较案例。
退出码：`0` 表示输入有效且没有失败，`1` 表示输入有效且存在失败，`2` 表示版本、
准入、验签、结构、密钥或输出不合法。
当前清单没有准入案例，CLI 会以 `2` 拒绝生成空洞的“成功”报告。

后端必须通过 `EVAL_REPORT_SIGNING_KEY` 配置同一签名密钥，未配置时同步接口返回 `503`。签名不匹配返回 `422`；同一 `report_id` 对应不同内容，或同一语义证据更换 ID 重放，返回 `409`。报告只包含匿名聚合，不包含原始案例 ID、用户文本或图片。
