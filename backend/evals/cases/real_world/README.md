# 真实案例评测集

这个目录只保存案例清单、人工标注和评测输入，不复制客户原始资产。资产通过 `manifest.json` 的相对路径引用，运行时必须显式指定允许的资产根目录。

## 案例准入

案例同时满足以下条件后才会进入离线评测：

- `consent_status` 为 `granted` 或明确无需授权的 `not_required`；
- `annotation_status` 为 `ready`，并填写非空 `label_version`；
- `allowed_purposes` 包含 `offline_evaluation`；
- `split` 已分配为 `development`、`regression` 或 `blind`；
- 资产存在且没有越过指定的资产根目录；
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
再以 `run-bindings.template.json` 记录内部案例 ID、任务 ID 和运行 ID。收集器只接受：

- 状态为 `completed` 且 task/run 归属一致的运行；
- `generator=llm`，不接受 template 降级、demo、mock、manual、test 或 synthetic；
- 存在完整的模型、Prompt、输入、输出快照和四个 Worker 节点；
- `generate_plans` 来自 LLM，报价与质量校验来自确定性节点；
- 同一证据包内每个已准入案例恰好一个运行，同一 run 不得跨案例复用。

收集器不会接收 CaseResult。当前可从运行事实确定性推导生成成功、有效 SKU 和报价一致性；需求、空间、布局和人工满意度在接入可追溯标注执行器前保持无证据，因此质量门禁会失败，不会用模拟值或手工值补齐。

证据包 2.0 使用独立 HMAC 密钥签名，绑定数据集内容指纹、匿名案例指纹、task/run ID、模型/Prompt/规则/数据版本，以及输入、输出和结果摘要。文件不包含案例 ID、资产路径、Prompt、输入或模型输出原文。签名密钥必须只配置在受控 Worker/CI，不应写入仓库、命令行或开发者共享环境。

跨用户访问和重试边界不能依靠默认零值证明安全。每个逐例结果必须分别填写实际执行的 `cross_user_access_checks` 和 `retry_bound_checks`；检查次数为 0 时，对应安全门禁输出 `NO EVIDENCE` 并失败。若记录了严重跨用户问题或无限重试，却没有对应检查证据，输入会被直接拒绝。

在仓库根目录运行：

```powershell
$env:PYTHONPATH = "backend"
$env:EVAL_EVIDENCE_KEY_ID = "quality-ci-2026-09"
$env:EVAL_EVIDENCE_HMAC_KEY = "从密钥管理服务注入的至少32字节随机密钥"
python -m evals.collect_real_world_evidence `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --run-bindings backend/evals/cases/real_world/run-bindings.json `
  --prompt-version prompt-2026-09-02 `
  --rules-version rules-2026-09-02 `
  --output backend/evals/reports/evidence/real_world_eval.evidence.json

python -m evals.run_real_world_eval `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --results backend/evals/reports/evidence/real_world_eval.evidence.json `
  --establish-baseline `
  --output-dir backend/evals/reports/real_world
```

`--establish-baseline` 只用于人工批准的首次基线建立。只要清单中存在准入案例，后续运行若未提供 `--baseline-report`，会以输入错误退出；因此模型、Prompt、规则或数据变更不能静默跳过版本比较。无准入案例时仍会生成失败报告，用于展示缺少哪些授权与标注证据。

模型、Prompt 或规则发生变化时，必须额外传入同一数据版本、同一案例集合生成的基线报告：

```powershell
python -m evals.run_real_world_eval `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --results backend/evals/reports/evidence/real_world_eval.evidence.json `
  --baseline-results backend/evals/reports/evidence/baseline.evidence.json `
  --output-dir backend/evals/reports/candidate
```

基线和候选的数据版本或准入案例 ID 不一致时拒绝比较。即使候选仍达到绝对门禁，只要比例指标下降、跨用户访问或无限重试计数增加，版本回归也会失败。

报告和签名证据会绑定准入案例的资产 SHA-256、标签版本、来源和分组。基线与候选即使沿用相同数据版本，只要实际资产、标签或分组发生变化，也会拒绝伪装成同一案例集比较。

评测退出码：`0` 表示全部门禁通过，`1` 表示可信证据完整但质量未达标，`2` 表示清单、证据、签名或密钥不合法。证据收集器成功返回 `0`，任何运行来源、覆盖或签名配置问题返回 `2`。当前清单没有准入案例，因此尚不能签发真实验收证据，也不能在 CI 中当作成功。

## 人工标注最小内容

每例至少保存：脱敏需求、人工确认的 RoomModel、低置信事实、允许商品范围、预算范围、确定性报价结果、布局硬约束、失败标签、标注人与标签版本。用户满意度和人工修改率单独记录，不与确定性事实指标混算。

## 失败样本分诊

质量门禁的逐例结果与失败分诊证据是两个独立契约。分诊输入使用
`failure_triage.template.json` 的 `schema_version=1.0` 和
`taxonomy_version=1.0`，`data_version` 必须与案例清单完全一致。每条记录只接受：

- 已准入案例的 `case_id`；
- 结构化 `code`、`failure_type` 和 `severity`；
- 结构化 `tags` 和 `metrics` 数组。

`failure_type` 1.0 支持 `requirement`、`space_fact`、`catalog`、`quote`、
`budget`、`layout`、`style`、`generation`、`security`、`orchestration`
和 `human_feedback`；`severity` 只支持 `critical`、`high`、`medium`、
`low`。标识符必须使用小写字母开头，后续只允许小写字母、数字、点、
下划线和连字符。未知字段和自由文本会被拒绝，不会参与启发式分类。

先分别配置 case_id 脱敏密钥和报告签名密钥，再运行 CLI。两把密钥用途不同，不能复用；命令输出中的 `sync_payload` 可直接作为管理员同步接口的 JSON 请求体：

```powershell
$env:EVAL_CASE_ID_SALT = "由评测管理员配置的至少16字符密钥"
$env:EVAL_REPORT_SIGNING_KEY = "由评测管理员配置的至少32字节独立签名密钥"
$env:PYTHONPATH = "backend"
python -m evals.run_failure_triage `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --failures backend/evals/cases/real_world/failure_triage.template.json `
  --salt-id eval-case-key-v1 `
  --report-id weekly-2026-W36 `
  --candidate-version candidate-2026-W36 `
  --signing-key-id eval-report-key-v1 `
  --output-dir backend/evals/reports/failure_triage
```

报告按失败类型、严重度、数据切分、code、tag 和 metric 聚合，并输出稳定的
HMAC case 别名。报告不保存原始 case_id，也不保存脱敏密钥；同一数据版本需要
保持相同密钥和 `salt-id`，才能跨次比较案例。退出码：`0` 表示输入有效且没有
失败，`1` 表示输入有效且存在失败，`2` 表示版本、准入、结构、密钥或输出不合法。
当前清单没有准入案例，CLI 会以 `2` 拒绝生成空洞的“成功”报告。

后端必须通过 `EVAL_REPORT_SIGNING_KEY` 配置同一签名密钥，未配置时同步接口返回 `503`。签名不匹配返回 `422`；同一 `report_id` 对应不同内容，或同一语义证据更换 ID 重放，返回 `409`。报告只包含匿名聚合，不包含原始案例 ID、用户文本或图片。
