import type { Furniture3DSpec, FurnitureMaterialSpec } from "@/types/furniture";
import { furnitureModelKind } from "@/lib/furnitureModelKind";

export interface DeterministicModelPart {
  部件ID: string;
  几何: "rounded_cushion" | "curved_cushion" | "wood_rail" | "tapered_wood_leg" | "tapered_wood_post";
  尺寸_mm: [number, number, number];
  位置_mm: [number, number, number];
  旋转_deg: [number, number, number];
  材质槽: string;
}

export interface DeterministicMaterialSlot extends FurnitureMaterialSpec {
  槽位ID: string;
  sheen?: number;
}

export interface DeterministicFurnitureRule {
  规则版本: string;
  规则状态: "ready";
  模型ID: string;
  生成器: "lounge_chair_v1";
  包围尺寸_mm: { 宽: number; 高: number; 深: number };
  材质槽: DeterministicMaterialSlot[];
  部件: DeterministicModelPart[];
}

export function deterministicFurnitureRule(
  spec: Furniture3DSpec,
): DeterministicFurnitureRule | undefined {
  const rule = (spec as Furniture3DSpec & {
    确定性建模规则?: DeterministicFurnitureRule;
  }).确定性建模规则;
  if (rule?.规则状态 !== "ready" || rule.生成器 !== "lounge_chair_v1") {
    return undefined;
  }
  return rule;
}

export function resolveFurnitureRenderer(spec: Furniture3DSpec):
  | { kind: "deterministic"; generator: DeterministicFurnitureRule["生成器"] }
  | { kind: "legacy"; generator: ReturnType<typeof furnitureModelKind> } {
  const rule = deterministicFurnitureRule(spec);
  if (rule) {
    return { kind: "deterministic", generator: rule.生成器 };
  }
  return {
    kind: "legacy",
    generator: furnitureModelKind(spec.家具类型 ?? ""),
  };
}

export function modelPartTransform(part: DeterministicModelPart) {
  return {
    size: part.尺寸_mm.map((value) => value / 1000) as [number, number, number],
    position: part.位置_mm.map((value) => value / 1000) as [number, number, number],
    rotation: part.旋转_deg.map((value) => value * Math.PI / 180) as [number, number, number],
  };
}
