# 公开参考数据边界

`public_reference_products.json` 是带观测时间的内部评估快照，只保存商品事实字段和官方来源链接，不包含或转载商品图片。

- 所有记录必须保持 `data_origin=public_reference` 和 `is_active=false`，不得进入本店报价目录。
- 价格不是实时价格，也不代表本店库存、授权经销或销售承诺。
- 不得将本目录扩展为联网爬虫或定时抓取任务。
- 对外展示、批量采集或生产经营使用前，必须重新核验来源条款并取得所需授权。
- 更新数据时必须同步更新 `source_retrieved_at`、`price_observed_at` 和来源 URL。
