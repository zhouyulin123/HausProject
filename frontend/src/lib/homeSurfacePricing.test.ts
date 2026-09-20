import { describe, expect, it } from "vitest";
import type { QuoteRule } from "@/api/designApi";
import {
  isSurfaceAreaQuoteRule,
  surfaceQuoteRuleFallbackLabel,
  surfaceQuoteRuleId,
  surfaceQuoteRuleLabel,
} from "./homeSurfacePricing";

const rule = (overrides: Partial<QuoteRule> = {}): QuoteRule => ({
  id: 7,
  project_name: "地面铺装",
  category: "表面材料",
  pricing_unit: "㎡",
  material_grade: "耐磨地板",
  unit_price: 100,
  region_codes: ["CN-SH"],
  waste_rate_bps: 1000,
  minimum_quantity: 10,
  installation_fee: 200,
  shipping_fee: 100,
  tax_rate_bps: 0,
  data_version: "browser-v1",
  record_version: 2,
  description: null,
  ...overrides,
});

describe("surface pricing helpers", () => {
  it("only accepts area rules and strict positive identifiers", () => {
    expect(isSurfaceAreaQuoteRule(rule())).toBe(true);
    expect(isSurfaceAreaQuoteRule(rule({ pricing_unit: "延米" }))).toBe(false);
    expect(surfaceQuoteRuleId("7")).toBe(7);
    expect(surfaceQuoteRuleId("7.5")).toBeUndefined();
    expect(surfaceQuoteRuleId(" 7")).toBeUndefined();
    expect(surfaceQuoteRuleId("")).toBeUndefined();
  });

  it("labels the commercial inputs and immutable record version", () => {
    expect(surfaceQuoteRuleLabel(rule())).toBe(
      "地面铺装 · 耐磨地板 · 100元/㎡ · CN-SH · 损耗 10% · 最低量 10㎡ · 安装 200元 · 运输 100元 · 税 0% · v2",
    );
  });

  it("distinguishes a read failure from a disabled or missing rule", () => {
    expect(surfaceQuoteRuleFallbackLabel(7, "error")).toBe(
      "规则详情暂未读取，保留绑定 #7",
    );
    expect(surfaceQuoteRuleFallbackLabel(7, "missing")).toContain("已停用或不存在");
  });
});
