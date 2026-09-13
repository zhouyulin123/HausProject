import type { FurnitureDataOrigin } from "@/types/furniture";

const labels: Record<FurnitureDataOrigin, string> = {
  development_fixture: "开发样本（模拟业务数据）",
  merchant: "商家提供",
  merchant_draft: "商家草稿",
  merchant_verified: "商家已核验",
  public_reference: "公开参考",
  verified: "已核验",
  demo: "演示数据",
  unknown: "未知来源",
};

export function getFurnitureDataOriginLabel(
  origin: FurnitureDataOrigin | undefined,
): string {
  return labels[origin ?? "unknown"] ?? labels.unknown;
}
