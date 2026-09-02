# 商品生命周期与报价快照

## 商用推荐门禁

商品只有同时满足以下条件才会进入模型上下文、方案回填和确定性替代：

- 商品启用，且不是 `public_reference`；
- `verification_status=verified`；
- 库存状态为现货、低库存，或交期完整的预售；
- 当前时间处于价格生效和失效时间之间；
- 目标地区可售；
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

升级数据库：

```powershell
cd backend
python -m alembic upgrade head
```
