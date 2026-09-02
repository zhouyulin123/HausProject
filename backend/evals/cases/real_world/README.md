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
