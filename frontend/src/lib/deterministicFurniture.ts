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
  外观规则: {
    软包: {
      滚边: { 启用: boolean; 直径_mm: number };
      缝线: { 启用: boolean; 线径_mm: number; 内缩_mm: number };
      绒面: { 方向性: boolean; 法线强度: number; 纹理周期_mm: number };
      坐垫形变: { 前缘压缩: number; 中心隆起_mm: number };
      靠背曲面: { 横向弧度半径_mm: number };
    };
  };
  材质槽: DeterministicMaterialSlot[];
  部件: DeterministicModelPart[];
}

export interface UpholsteryAppearance {
  pipingEnabled: boolean;
  pipingRadius: number;
  seamEnabled: boolean;
  seamRadius: number;
  seamInset: number;
  normalStrength: number;
  fabricPeriod: number;
  directionalNap: boolean;
  frontCompression: number;
  crown: number;
  backCurveRadius: number;
}

export function upholsteryAppearance(
  rule: DeterministicFurnitureRule,
): UpholsteryAppearance {
  const upholstery = rule.外观规则.软包;
  return {
    pipingEnabled: upholstery.滚边.启用,
    pipingRadius: upholstery.滚边.直径_mm / 2000,
    seamEnabled: upholstery.缝线.启用,
    seamRadius: upholstery.缝线.线径_mm / 2000,
    seamInset: upholstery.缝线.内缩_mm / 1000,
    normalStrength: upholstery.绒面.法线强度,
    fabricPeriod: upholstery.绒面.纹理周期_mm / 1000,
    directionalNap: upholstery.绒面.方向性,
    frontCompression: upholstery.坐垫形变.前缘压缩,
    crown: upholstery.坐垫形变.中心隆起_mm / 1000,
    backCurveRadius: upholstery.靠背曲面.横向弧度半径_mm / 1000,
  };
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function cushionVertexPosition(
  geometry: DeterministicModelPart["几何"],
  vertex: [number, number, number],
  size: [number, number, number],
  appearance: UpholsteryAppearance,
): [number, number, number] {
  const [x, y, z] = vertex;
  if (geometry === "curved_cushion") {
    const halfWidth = size[0] / 2;
    const normalizedX = clamp01(Math.abs(x) / halfWidth);
    const radius = Math.max(appearance.backCurveRadius, halfWidth);
    const centerForward = radius - Math.sqrt(radius ** 2 - halfWidth ** 2);
    return [x, y, z + centerForward * (1 - normalizedX ** 2)];
  }
  if (geometry === "rounded_cushion") {
    const halfWidth = size[0] / 2;
    const halfDepth = size[2] / 2;
    const frontWeight = clamp01(z / halfDepth);
    const xProfile = 1 - clamp01(Math.abs(x) / halfWidth) ** 2;
    const zProfile = 1 - clamp01(Math.abs(z) / halfDepth) ** 2;
    const surfaceSign = Math.sign(y);
    const compressedY = y * (1 - appearance.frontCompression * frontWeight);
    return [x, compressedY + surfaceSign * appearance.crown * xProfile * zProfile, z];
  }
  return vertex;
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

export function taperedPartPivotTransform(part: DeterministicModelPart) {
  const { size, position, rotation } = modelPartTransform(part);
  return {
    pivot: [position[0], position[1] - size[1] / 2, position[2]] as [number, number, number],
    childCenter: [0, size[1] / 2, 0] as [number, number, number],
    rotation,
    size,
  };
}
