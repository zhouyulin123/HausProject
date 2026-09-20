import type { QuoteRule } from "@/api/designApi";

const AREA_UNITS = new Set(["m2", "m²", "㎡"]);

export function isSurfaceAreaQuoteRule(rule: QuoteRule): boolean {
  return AREA_UNITS.has(rule.pricing_unit.trim().toLowerCase());
}

export function surfaceQuoteRuleId(value: FormDataEntryValue | null): number | undefined {
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) return undefined;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : undefined;
}

export function surfaceQuoteRuleLabel(rule: QuoteRule): string {
  const grade = rule.material_grade ? ` · ${rule.material_grade}` : "";
  const regions = rule.region_codes.length
    ? rule.region_codes.includes("*")
      ? "全部地区"
      : rule.region_codes.join("/")
    : "全部地区";
  const terms = [
    `损耗 ${rule.waste_rate_bps / 100}%`,
    `最低量 ${rule.minimum_quantity}${rule.pricing_unit}`,
    `安装 ${rule.installation_fee}元`,
    `运输 ${rule.shipping_fee}元`,
    `税 ${rule.tax_rate_bps / 100}%`,
  ].join(" · ");
  return `${rule.project_name}${grade} · ${rule.unit_price}元/${rule.pricing_unit} · ${regions} · ${terms} · v${rule.record_version}`;
}

export function surfaceQuoteRuleFallbackLabel(
  id: number,
  status: "loading" | "error" | "missing",
): string {
  if (status === "loading") return `正在读取当前规则 #${id}`;
  if (status === "error") return `规则详情暂未读取，保留绑定 #${id}`;
  return `当前规则 #${id} 已停用或不存在`;
}
