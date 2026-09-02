import type { AgentPendingQuestion } from "@/types/agent";
import type {
  CabinetCustomFurnitureSpec,
  CustomFurnitureFamily,
  CustomFurniturePreviewResult,
  CustomFurnitureQuotePreview,
  CustomFurnitureSpec,
  CustomFurnitureSpecPatch,
  TableCustomFurnitureSpec,
} from "@/types/customFurniture";

export const CABINET_PURPOSES = [
  ["wardrobe", "衣柜"],
  ["entryway_cabinet", "玄关柜"],
  ["bookcase", "书柜"],
  ["balcony_storage", "阳台储物柜"],
] as const;
export const TABLE_PURPOSES = [
  ["dining_table", "餐桌"],
  ["desk", "书桌"],
  ["kitchen_island", "岛台"],
] as const;
export const CABINET_MATERIALS = [
  "E0 颗粒板",
  "多层实木",
  "实木（橡木）",
  "E0 颗粒板（防潮封边）",
] as const;
export const TABLE_MATERIALS = [
  "实木（橡木）",
  "岩板 + 金属",
  "多层实木 + 岩板台面",
] as const;

export function createCustomFurnitureDraft(
  family: "cabinet",
): CabinetCustomFurnitureSpec;
export function createCustomFurnitureDraft(family: "table"): TableCustomFurnitureSpec;
export function createCustomFurnitureDraft(
  family: CustomFurnitureFamily,
): CustomFurnitureSpec;
export function createCustomFurnitureDraft(
  family: CustomFurnitureFamily,
): CustomFurnitureSpec {
  if (family === "cabinet") {
    return {
      family,
      name: "主卧定制衣柜",
      purpose: "wardrobe",
      material: "E0 颗粒板",
      dimensions: { width_mm: 1800, height_mm: 2400, depth_mm: 600 },
      structure: {
        door_style: "hinged",
        door_count: 4,
        compartment_count: 4,
        shelf_count: 5,
        drawer_count: 2,
        panel_thickness_mm: 18,
        leg_height_mm: 0,
      },
    };
  }
  return {
    family,
    name: "六人位定制餐桌",
    purpose: "dining_table",
    material: "实木（橡木）",
    dimensions: { width_mm: 1600, height_mm: 750, depth_mm: 800 },
    structure: {
      top_shape: "rectangle",
      base_style: "four_leg",
      support_count: 4,
      seat_count: 6,
      top_thickness_mm: 36,
      edge_radius_mm: 12,
    },
  };
}

export function customFurnitureDraftFromSpec(
  spec: CustomFurnitureSpecPatch | null,
): CustomFurnitureSpec {
  const family = spec?.family ?? "cabinet";
  const base = createCustomFurnitureDraft(family);
  const purposeOptions = family === "cabinet" ? CABINET_PURPOSES : TABLE_PURPOSES;
  const materialOptions = family === "cabinet" ? CABINET_MATERIALS : TABLE_MATERIALS;
  const shared = {
    ...(spec?.name ? { name: spec.name } : {}),
    ...(spec?.purpose && purposeOptions.some(([value]) => value === spec.purpose)
      ? { purpose: spec.purpose }
      : {}),
    ...(spec?.material && materialOptions.some((value) => value === spec.material)
      ? { material: spec.material }
      : {}),
    dimensions: { ...base.dimensions, ...spec?.dimensions },
  };
  if (family === "cabinet") {
    const cabinet = createCustomFurnitureDraft("cabinet");
    return {
      ...cabinet,
      ...shared,
      purpose: CABINET_PURPOSES.some(([value]) => value === spec?.purpose)
        ? spec!.purpose as CabinetCustomFurnitureSpec["purpose"]
        : cabinet.purpose,
      material: CABINET_MATERIALS.includes(spec?.material as CabinetCustomFurnitureSpec["material"])
        ? spec!.material as CabinetCustomFurnitureSpec["material"]
        : cabinet.material,
      structure: {
        ...cabinet.structure,
        ...Object.fromEntries(
          Object.keys(cabinet.structure).map((key) => [
            key,
            spec?.structure?.[key as keyof typeof spec.structure]
              ?? cabinet.structure[key as keyof typeof cabinet.structure],
          ]),
        ),
      },
    };
  }
  const table = createCustomFurnitureDraft("table");
  return {
    ...table,
    ...shared,
    purpose: TABLE_PURPOSES.some(([value]) => value === spec?.purpose)
      ? spec!.purpose as TableCustomFurnitureSpec["purpose"]
      : table.purpose,
    material: TABLE_MATERIALS.includes(spec?.material as TableCustomFurnitureSpec["material"])
      ? spec!.material as TableCustomFurnitureSpec["material"]
      : table.material,
    structure: {
      ...table.structure,
      ...Object.fromEntries(
        Object.keys(table.structure).map((key) => [
          key,
          spec?.structure?.[key as keyof typeof spec.structure]
            ?? table.structure[key as keyof typeof table.structure],
        ]),
      ),
    },
  };
}

export type CustomFurnitureFocusField =
  | "family"
  | "name"
  | "purpose"
  | "material"
  | "dimensions"
  | "structure";

export function customFurnitureFocusField(
  questions: AgentPendingQuestion[],
): CustomFurnitureFocusField | null {
  for (const question of questions) {
    const match = /^custom_furniture_spec\.(family|name|purpose|material|dimensions|structure)$/.exec(
      question.field,
    );
    if (match) return match[1] as CustomFurnitureFocusField;
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseCustomFurniturePreview(
  value: unknown,
): CustomFurniturePreviewResult | null {
  if (!isRecord(value) || !["preview_ready", "needs_human"].includes(String(value.status))) {
    return null;
  }
  if (!isRecord(value.spec) || !["cabinet", "table"].includes(String(value.spec.family))) {
    return null;
  }
  if (!isRecord(value.model_spec) || !isRecord(value.model_spec.确定性建模规则)) {
    return null;
  }
  const rule = value.model_spec.确定性建模规则;
  if (
    rule.规则状态 !== "ready" ||
    !["cabinet_v2", "table_v2"].includes(String(rule.生成器)) ||
    !Array.isArray(rule.材质槽) ||
    !Array.isArray(rule.部件)
  ) {
    return null;
  }
  if (!isRecord(value.quote_preview) || !["estimated", "needs_human"].includes(String(value.quote_preview.status))) {
    return null;
  }
  if (!Array.isArray(value.warnings) || !value.warnings.every((item) => typeof item === "string")) {
    return null;
  }
  return value as unknown as CustomFurniturePreviewResult;
}

const quoteReasons = {
  quote_rule_missing: "未找到唯一可复算的报价规则",
  quote_rule_ambiguous: "匹配到多条报价规则，需要人工确认",
  quote_rule_invalid: "报价规则缺少有效单价或计价单位",
} as const;

export function quotePreviewDisplay(quote: CustomFurnitureQuotePreview): {
  amount: string | null;
  state: string;
  reason: string;
} {
  if (quote.status !== "estimated" || quote.estimated_amount === null) {
    return {
      amount: null,
      state: "待人工报价",
      reason: quote.reason_code ? quoteReasons[quote.reason_code] : "报价需要人工确认",
    };
  }
  const amount = Number(quote.estimated_amount);
  return {
    amount: Number.isFinite(amount)
      ? new Intl.NumberFormat("zh-CN", {
          style: "currency",
          currency: "CNY",
          minimumFractionDigits: 2,
        }).format(amount)
      : null,
    state: "确定性估算",
    reason: quote.rule_id ? `报价规则 #${quote.rule_id}` : "确定性报价规则",
  };
}
