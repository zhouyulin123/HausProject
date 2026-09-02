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

## 结果格式

执行器以 `results.template.json` 为起点，为每个已准入案例写入一条结果。计数字段必须来自确定性检查或人工标签，LLM Judge 结果不能替代 SKU、报价、权限、低置信确认和空间硬约束证据。

在仓库根目录运行：

```powershell
$env:PYTHONPATH = "backend"
python -m evals.run_real_world_eval `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --results backend/evals/cases/real_world/results.template.json `
  --output-dir backend/evals/reports/real_world
```

模型、Prompt 或规则发生变化时，必须额外传入同一数据版本、同一案例集合生成的基线报告：

```powershell
python -m evals.run_real_world_eval `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --results backend/evals/cases/real_world/results.template.json `
  --baseline-report backend/evals/reports/baseline/real_world_eval.json `
  --output-dir backend/evals/reports/candidate
```

基线和候选的数据版本或准入案例 ID 不一致时拒绝比较。即使候选仍达到绝对门禁，只要比例指标下降、跨用户访问或无限重试计数增加，版本回归也会失败。

退出码：`0` 表示全部门禁通过，`1` 表示证据完整但质量未达标，`2` 表示清单或结果输入不合法。当前模板没有准入案例，因此预期退出码为 `1`，不能在 CI 中当作成功。

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

先通过受控密钥配置 case_id 脱敏，再运行 CLI：

```powershell
$env:EVAL_CASE_ID_SALT = "由评测管理员配置的至少16字符密钥"
$env:PYTHONPATH = "backend"
python -m evals.run_failure_triage `
  --manifest backend/evals/cases/real_world/manifest.json `
  --asset-root . `
  --failures backend/evals/cases/real_world/failure_triage.template.json `
  --salt-id eval-case-key-v1 `
  --output-dir backend/evals/reports/failure_triage
```

报告按失败类型、严重度、数据切分、code、tag 和 metric 聚合，并输出稳定的
HMAC case 别名。报告不保存原始 case_id，也不保存脱敏密钥；同一数据版本需要
保持相同密钥和 `salt-id`，才能跨次比较案例。退出码：`0` 表示输入有效且没有
失败，`1` 表示输入有效且存在失败，`2` 表示版本、准入、结构、密钥或输出不合法。
当前清单没有准入案例，CLI 会以 `2` 拒绝生成空洞的“成功”报告。
