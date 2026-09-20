import type { HomeQuote } from "@/types/homeDesign";

type QuoteLine = HomeQuote["snapshot"]["lines"][number];

export interface SurfaceQuoteEvidence {
  project: string;
  grade: string | null;
  pricingUnit: string;
  requestedQuantity: number;
  billableQuantity: number;
  wasteRateBps: number;
  minimumQuantity: number;
  baseSubtotal: number;
  installationFee: number;
  shippingFee: number;
  taxRateBps: number;
  taxAmount: number;
  subtotal: number;
  dataVersion: string;
  recordVersion: number;
}

export function readSurfaceQuoteEvidence(
  value: QuoteLine["rule_evidence"] | undefined,
): SurfaceQuoteEvidence | null {
  if (!value || value.schemaVersion !== "1.0") return null;
  const number = (key: string) => value[key];
  const numericKeys = [
    "requestedQuantity",
    "billableQuantity",
    "wasteRateBps",
    "minimumQuantity",
    "baseSubtotal",
    "installationFee",
    "shippingFee",
    "taxRateBps",
    "taxAmount",
    "subtotal",
    "recordVersion",
  ];
  if (numericKeys.some((key) => !Number.isFinite(number(key)))) return null;
  if (
    typeof value.project !== "string" ||
    typeof value.pricingUnit !== "string" ||
    typeof value.dataVersion !== "string" ||
    (value.grade !== null && typeof value.grade !== "string")
  )
    return null;
  return value as unknown as SurfaceQuoteEvidence;
}

const amount = (value: number, currency: string) =>
  `${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} ${currency}`;

export default function HomeQuoteEvidence({
  evidence,
  currency,
}: {
  evidence: QuoteLine["rule_evidence"] | undefined;
  currency: string;
}) {
  const item = readSurfaceQuoteEvidence(evidence);
  if (!item) return null;
  return (
    <div className="hd-quote-evidence">
      <small>
        {item.project}
        {item.grade ? ` · ${item.grade}` : ""} · 数据 {item.dataVersion} · 规则 V
        {item.recordVersion}
      </small>
      <small>
        请求量 {item.requestedQuantity} {item.pricingUnit} · 计费量 {item.billableQuantity}{" "}
        {item.pricingUnit} · 损耗 {item.wasteRateBps / 100}% · 最低量 {item.minimumQuantity}{" "}
        {item.pricingUnit}
      </small>
      <small>
        基础 {amount(item.baseSubtotal, currency)} · 安装 {amount(item.installationFee, currency)} ·
        运输 {amount(item.shippingFee, currency)} · 税 {item.taxRateBps / 100}%（
        {amount(item.taxAmount, currency)}） · 冻结小计 {amount(item.subtotal, currency)}
      </small>
    </div>
  );
}
