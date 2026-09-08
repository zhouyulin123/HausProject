import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AdminProduct } from "@/api/designApi";
import {
  CatalogReadinessSummary,
  ProductCommercialFacts,
  filterAdminProducts,
} from "./AdminPage";

function product(
  id: number,
  name: string,
  verification: AdminProduct["verification_status"],
): AdminProduct {
  return {
    id,
    sku: `SKU-${id}`,
    name,
    category: "沙发",
    room: "客厅",
    style: "现代简约",
    material: "布艺",
    price: 3999,
    price_max: null,
    price_text: "¥3,999",
    size: null,
    selling_point: null,
    alternative: null,
    image_url: null,
    model_url: null,
    model_status: "missing",
    model_width_mm: null,
    model_height_mm: null,
    model_depth_mm: null,
    model_license: null,
    model_source: null,
    model_reviewed_at: null,
    model_reviewed_by: null,
    model_review_note: null,
    data_origin: "merchant_draft",
    source_name: "供应商目录",
    source_url: "https://supplier.example/item",
    source_product_id: `SKU-${id}`,
    source_retrieved_at: "2026-09-01T00:00:00Z",
    price_observed_at: "2026-09-01T00:00:00Z",
    price_note: null,
    source_metadata: null,
    verification_status: verification,
    availability_status: "unknown",
    region_codes: ["CN-SH"],
    stock_quantity: null,
    lead_time_days_min: null,
    lead_time_days_max: null,
    price_valid_from: "2026-09-01T00:00:00Z",
    price_valid_to: "2026-12-31T23:59:59Z",
    verified_at: null,
    verified_by: null,
    data_version: "catalog-test-v1",
    record_version: 2,
    alternative_skus: [],
    eligibility: {
      eligible: false,
      reason_codes: ["availability_unknown"],
    },
  };
}

describe("商品商业核验列表", () => {
  const products = [
    product(1, "待核验沙发", "draft"),
    product(2, "已核验沙发", "verified"),
  ];

  it("可同时按关键词和核验状态筛选", () => {
    expect(filterAdminProducts(products, "沙发", "verified").map(({ id }) => id)).toEqual([2]);
    expect(filterAdminProducts(products, "SKU-1", "all").map(({ id }) => id)).toEqual([1]);
  });

  it("直接显示不可推荐原因、来源和数据版本", () => {
    const html = renderToStaticMarkup(<ProductCommercialFacts product={products[0]} />);
    expect(html).toContain("库存状态未知");
    expect(html).toContain("不可推荐");
    expect(html).toContain("供应商目录");
    expect(html).toContain("catalog-test-v1");
    expect(html).toContain("r2");
  });

  it("就绪摘要显示地区、可推荐数量和真实阻断原因", () => {
    const html = renderToStaticMarkup(
      <CatalogReadinessSummary
        readiness={{
          checked_at: "2026-09-08T12:00:00Z",
          region: "CN-SH",
          total: 57,
          active_total: 57,
          inactive_total: 0,
          eligible_total: 12,
          ineligible_total: 45,
          verification_status_counts: { draft: 40, verified: 17 },
          availability_status_counts: { unknown: 40, in_stock: 17 },
          data_origin_counts: { merchant_draft: 40, merchant: 17 },
          reason_code_counts: { verification_required: 40 },
        }}
        loading={false}
        error=""
        onRetry={() => undefined}
      />,
    );
    expect(html).toContain("CN-SH");
    expect(html).toContain("可推荐");
    expect(html).toContain(">12<");
    expect(html).toContain("缺少商业核验");
    expect(html).toContain(">40<");
  });

  it("就绪摘要失败时显示重试入口而不是零值", () => {
    const html = renderToStaticMarkup(
      <CatalogReadinessSummary
        readiness={null}
        loading={false}
        error="目录就绪度加载失败"
        onRetry={() => undefined}
      />,
    );
    expect(html).toContain("目录就绪度加载失败");
    expect(html).toContain("重试");
    expect(html).not.toContain("可推荐 0");
  });
});
