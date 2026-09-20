import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import HomeQuoteEvidence, { readSurfaceQuoteEvidence } from "./HomeQuoteEvidence";

const evidence = {
  schemaVersion: "1.0",
  project: "地面铺装",
  grade: "耐磨地板",
  pricingUnit: "㎡",
  requestedQuantity: 30,
  billableQuantity: 33,
  wasteRateBps: 1000,
  minimumQuantity: 10,
  baseSubtotal: 3300,
  installationFee: 200,
  shippingFee: 100,
  taxRateBps: 0,
  taxAmount: 0,
  subtotal: 3600,
  dataVersion: "catalog-2026-09",
  recordVersion: 4,
};

describe("材料估价冻结证据", () => {
  it("逐项展示服务端证据，不把请求量冒充计费量", () => {
    const html = renderToStaticMarkup(
      <HomeQuoteEvidence evidence={evidence} currency="CNY" />,
    );
    expect(html).toContain("请求量 30");
    expect(html).toContain("计费量 33");
    expect(html).toContain("损耗 10%");
    expect(html).toContain("安装 200 CNY");
    expect(html).toContain("运输 100 CNY");
    expect(html).toContain("冻结小计 3,600 CNY");
    expect(html).toContain("catalog-2026-09");
  });

  it("证据缺字段时不猜测或重算", () => {
    expect(readSurfaceQuoteEvidence({ ...evidence, billableQuantity: undefined })).toBeNull();
  });
});
