# 商品生命周期与报价快照

## 商用推荐门禁

商品只有同时满足以下条件才会进入模型上下文、方案回填和确定性替代：

- 商品启用，且不是 `public_reference`；
- `verification_status=verified`；
- 库存状态为现货、低库存，或交期完整的预售；
- 当前时间处于价格生效和失效时间之间；
- 目标地区可售；地区限定商品在调用方未提供地区时也不会进入推荐，只有 `*` 表示全国/全区域；
- 物理尺寸完整，并满足调用方给出的空间上限；
- 单价和累计商品金额不超过调用方预算。

`is_product_eligible` 是以上规则的单一实现，失败时返回稳定的 `reason_codes`。公开参考商品即使被误设为启用或草稿预览开关开启，也不会进入商用推荐。

## 40 条内部商品初稿

迁移不会根据旧 `source_metadata` 自动推断核验状态。现有数据，包括 `merchant_draft`，迁移后均为：

- `verification_status=draft`
- `availability_status=unknown`
- `record_version=1`

可以继续通过 `products_import.xlsx` 或商品 API 编辑。人工需要补齐库存、地区、交期、价格有效期、尺寸、数据版本和复核负责人，再设置为已核验。任何价格、库存、地区、有效期或尺寸字段后续发生变化，API 会增加 `record_version` 并自动退回草稿，要求重新核验。

## 确定性替代

替代选择先读取结构化 `alternative_skus`，再按同类别、同空间、价格接近度和 SKU 稳定排序。候选仍必须通过同一资格门禁，返回 `explicit_alternative`、`same_category`、`same_room`、`price_not_higher`、`dimensions_fit` 等原因代码，不由 LLM 编造 SKU。

## 历史报价

`QuoteSnapshot` 保存 `catalog_version`、`price_version`、`rule_version`、使用的 SKU 数据版本及完整行项目。`recalculate_quote_snapshot` 只使用快照中的数量和单价复算，不查询当前商品库，因此商品价格更新不会改变历史报价。

## 每周方案来源抽检

审计只接受由受控流程签名的生产验收 cohort，不会根据历史状态、生成器、日期或 seed 自动把旧 Demo 认定为生产数据。manifest 必须使用如下严格结构，并以去掉 `attestation` 后的 JSON（UTF-8、键排序、无多余空白）作为 HMAC-SHA256 签名输入：

```json
{
  "schema_version": "1.0",
  "cohort_kind": "production_acceptance",
  "cohort_id": "prod-acceptance-2026-w36",
  "cutover_id": "release-2026-w36",
  "environment": "production-cn",
  "issued_at": "2026-09-08T00:00:00+08:00",
  "members": [
    {"task_id": 101, "plan_version_id": 501}
  ],
  "attestation": {
    "algorithm": "hmac-sha256",
    "key_id": "traceability-cohort-v1",
    "signature": "<64 位小写十六进制签名>"
  }
}
```

`task_id` 与 `plan_version_id` 必须精确绑定数据库事实；成员不存在、跨任务、非 completed、重复或签名/环境不匹配都作为门禁失败，不能被抽样查询过滤。密钥只能由受控执行环境提供，禁止写入 manifest、命令行或报告：

```powershell
$env:PLAN_TRACEABILITY_COHORT_KEY_ID = "traceability-cohort-v1"
$env:PLAN_TRACEABILITY_COHORT_HMAC_KEY = "<从受保护密钥库注入>"
$env:PLAN_TRACEABILITY_COHORT_MANIFEST = "<受保护目录>\traceability-cohort.json"
python audit_plan_traceability.py `
  --cohort-manifest $env:PLAN_TRACEABILITY_COHORT_MANIFEST `
  --environment production-cn `
  --sample-size 20 `
  --output .test_artifacts/traceability-2026-W36.json
```

`sample-size` 只定义最低验收数量；签名 cohort 中的全部成员都会核验，不能用 seed 选出子集或跳过坏样本。退出码 `0` 表示通过，`1` 表示质量门禁失败，`2` 表示 manifest、验签、参数、数据库或输出文件错误。每周保留签名 manifest 和 JSON 报告；报告记录 cohort、cutover、环境、manifest 摘要、签名 key_id、成员绑定结果及核验原因码，不包含密钥。

升级数据库：

```powershell
cd backend
python -m alembic upgrade head
```
