import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApiError, type AdminProduct } from "@/api/designApi";
import ProductFormModal, {
  productSaveErrorMessage,
  validateProductDraft,
} from "./ProductFormModal";

const verifiedProduct: AdminProduct = {
  id: 8,
  sku: "SOFA-008",
  name: "核验沙发",
  category: "沙发",
  room: "客厅",
  style: "现代简约",
  material: "布艺",
  price: 4999,
  price_max: null,
  price_text: "¥4,999",
  size: "2200 x 950 x 820 mm",
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
  data_origin: "merchant",
  source_name: "供应商目录",
  source_url: "https://supplier.example/sofa-008",
  source_product_id: "SOFA-008",
  source_retrieved_at: "2026-09-01T08:00:00Z",
  price_observed_at: "2026-09-01T08:00:00Z",
  price_note: null,
  source_metadata: null,
  verification_status: "verified",
  availability_status: "in_stock",
  region_codes: ["CN-SH"],
  stock_quantity: 12,
  lead_time_days_min: 3,
  lead_time_days_max: 7,
  price_valid_from: "2026-09-01T00:00:00Z",
  price_valid_to: "2026-12-31T23:59:59Z",
  verified_at: "2026-09-01T09:00:00Z",
  verified_by: "user:1",
  data_version: "catalog-2026-q3",
  record_version: 4,
  alternative_skus: [],
  eligibility: { eligible: true, reason_codes: [] },
};

describe("商品商业核验表单", () => {
  it("展示来源、库存、地区、交期、有效期和数据版本字段", () => {
    const html = renderToStaticMarkup(
      <ProductFormModal initial={verifiedProduct} onClose={() => undefined} onSaved={() => undefined} />,
    );

    for (const label of [
      "数据来源",
      "来源名称",
      "来源链接",
      "核验状态",
      "可售状态",
      "销售地区",
      "库存数量",
      "最短交期",
      "最长交期",
      "价格生效时间",
      "价格失效时间",
      "数据版本",
    ]) {
      expect(html).toContain(label);
    }
  });

  it("不允许在商业事实不完整时标记为已核验", () => {
    expect(validateProductDraft({
      ...verifiedProduct,
      source_url: null,
      source_product_id: null,
      region_codes: [],
      price_valid_to: null,
    })).toContain("标记为已核验前，请补全来源链接或商品编号、销售地区和价格有效期");
  });

  it("供应商离线目录可用来源商品编号替代链接", () => {
    expect(validateProductDraft({ ...verifiedProduct, source_url: null })).toBeNull();
  });

  it("核验商业事实但不把缺货错误解释为来源未核验", () => {
    expect(validateProductDraft({
      ...verifiedProduct,
      availability_status: "out_of_stock",
      stock_quantity: 0,
    })).toBeNull();
  });

  it("已核验商品必须使用非草稿数据版本", () => {
    expect(validateProductDraft({ ...verifiedProduct, data_version: "draft-v1" }))
      .toContain("正式数据版本");
  });

  it("商家草稿、公开参考和演示来源不能直接标为已核验", () => {
    for (const data_origin of ["merchant_draft", "public_reference", "demo"] as const) {
      expect(validateProductDraft({ ...verifiedProduct, data_origin }))
        .toContain("可核验商业来源");
    }
  });

  it("把并发版本冲突转换为可执行的刷新提示", () => {
    const error = new ApiError("/api/products/8 -> 409", 409, {
      code: "record_version_conflict",
    });
    expect(productSaveErrorMessage(error)).toBe("商品已被其他运营人员更新，请关闭窗口并刷新后重试");
  });
});
