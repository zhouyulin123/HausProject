import type { Furniture3DSpec, FurnitureMaterialSpec } from "@/types/furniture";
import { furnitureModelKind } from "@/lib/furnitureModelKind";

export interface DeterministicModelPart {
  部件ID: string;
  几何:
    | "rounded_box"
    | "rounded_cushion"
    | "curved_cushion"
    | "rounded_tabletop"
    | "cloud_tabletop"
    | "elliptical_tabletop"
    | "wood_rail"
    | "tapered_wood_leg"
    | "top_pivot_tapered_wood_leg"
    | "tapered_wood_post"
    | "cylinder"
    | "frustum"
    | "tube"
    | "rug_panel"
    | "curtain_panel"
    | "mesh_panel"
    | "sphere"
    | "torus";
  尺寸_mm: [number, number, number];
  位置_mm: [number, number, number];
  旋转_deg: [number, number, number];
  材质槽: string;
  平面圆角半径_mm?: number;
  边缘圆角_mm?: number;
  圆角_mm?: number;
  顶部直径_mm?: number;
  底部直径_mm?: number;
  褶皱周期_mm?: number;
  网格间距_mm?: number;
  图案?: string;
}

export interface DeterministicMaterialSlot extends FurnitureMaterialSpec {
  槽位ID: string;
  表面类型?: "wood" | "fabric" | "metal" | "glass" | "stone" | "paper" | "rattan" | "mesh" | "generic";
  sheen?: number;
}

export interface DeterministicFurnitureRule {
  规则版本: string;
  规则状态: "ready";
  模型ID: string;
  生成器:
    | "lounge_chair_v1"
    | "coffee_table_v1"
    | "sofa_v2"
    | "table_v2"
    | "chair_v2"
    | "bed_v2"
    | "lamp_v2"
    | "rug_v2"
    | "curtain_v2"
    | "cabinet_v2"
    | "desk_v2"
    | "shelf_v2"
    | "ergonomic_chair_v2";
  包围尺寸_mm: { 宽: number; 高: number; 深: number };
  预览规则?: { 中心_mm: [number, number, number]; 半径_mm: number };
  外观规则: {
    软包?: {
      滚边: { 启用: boolean; 直径_mm: number };
      缝线: { 启用: boolean; 线径_mm: number; 内缩_mm: number };
      绒面: { 方向性: boolean; 法线强度: number; 纹理周期_mm: number };
      坐垫形变: { 前缘压缩: number; 中心隆起_mm: number };
      靠背曲面: { 横向弧度半径_mm: number };
    };
    木材?: {
      树种: string;
      纹理周期_mm: number;
      法线强度: number;
      透明面漆: { 强度: number; 粗糙度: number };
      榫卯节点: { 启用: boolean; 榫肩线宽_mm: number; 距构件端部_mm: number };
    };
  };
  材质槽: DeterministicMaterialSlot[];
  部件: DeterministicModelPart[];
}

export type LocalAxis = "x" | "y" | "z";

export interface WoodAppearance {
  species: string;
  grainPeriod: number;
  normalStrength: number;
  clearcoat: number;
  clearcoatRoughness: number;
  joineryEnabled: boolean;
  shoulderLineWidth: number;
  shoulderInset: number;
}

export function woodAppearance(rule: DeterministicFurnitureRule): WoodAppearance {
  const wood = rule.外观规则.木材;
  if (!wood) throw new Error("规则没有木材外观数据");
  return {
    species: wood.树种,
    grainPeriod: wood.纹理周期_mm / 1000,
    normalStrength: wood.法线强度,
    clearcoat: wood.透明面漆.强度,
    clearcoatRoughness: wood.透明面漆.粗糙度,
    joineryEnabled: wood.榫卯节点.启用,
    shoulderLineWidth: wood.榫卯节点.榫肩线宽_mm / 1000,
    shoulderInset: wood.榫卯节点.距构件端部_mm / 1000,
  };
}

export function woodGrainAxis(part: DeterministicModelPart): LocalAxis {
  const longestIndex = part.尺寸_mm.indexOf(Math.max(...part.尺寸_mm));
  return (["x", "y", "z"] as const)[longestIndex];
}

export function woodJoineryMarkers(
  part: DeterministicModelPart,
  appearance: WoodAppearance,
): Array<{ axis: LocalAxis; offset: number }> {
  if (!appearance.joineryEnabled || part.几何 !== "wood_rail") return [];
  const axis = woodGrainAxis(part);
  const axisIndex = { x: 0, y: 1, z: 2 }[axis];
  const length = part.尺寸_mm[axisIndex] / 1000;
  const offset = Math.max(0, length / 2 - appearance.shoulderInset);
  return [
    { axis, offset: -offset },
    { axis, offset },
  ];
}

export function previewLighting(radius: number) {
  const scaled = (factor: number) => Number((radius * factor).toFixed(4));
  return {
    ambientIntensity: 0.22,
    hemisphereIntensity: 0.62,
    key: {
      position: [scaled(2.8), scaled(4.2), scaled(2.2)] as [number, number, number],
      intensity: 1.75,
      color: "#FFF2DE",
    },
    fill: {
      position: [scaled(-2.4), scaled(2.2), scaled(3)] as [number, number, number],
      intensity: 0.48,
      color: "#DDE8F2",
    },
    rim: {
      position: [scaled(0.8), scaled(3.4), scaled(-2.8)] as [number, number, number],
      intensity: 0.72,
      color: "#FFE2BF",
    },
  };
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
  if (!upholstery) throw new Error("规则没有软包外观数据");
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
  if (
    rule?.规则状态 !== "ready"
    || !([
      "lounge_chair_v1",
      "coffee_table_v1",
      "sofa_v2",
      "table_v2",
      "chair_v2",
      "bed_v2",
      "lamp_v2",
      "rug_v2",
      "curtain_v2",
      "cabinet_v2",
      "desk_v2",
      "shelf_v2",
      "ergonomic_chair_v2",
    ] as DeterministicFurnitureRule["生成器"][]).includes(rule.生成器)
  ) {
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

export function roundPartScale(
  part: DeterministicModelPart,
): [number, number, number] {
  const [diameterX, , diameterZ] = part.尺寸_mm;
  return [1, 1, diameterX > 0 ? diameterZ / diameterX : 1];
}

export function structuralSurfacePixels(
  resolution: number,
  mesh: boolean,
): Uint8Array {
  const data = new Uint8Array(resolution * resolution * 4);
  for (let y = 0; y < resolution; y += 1) {
    for (let x = 0; x < resolution; x += 1) {
      const value = mesh
        ? (x % 8 < 2 || y % 8 < 2 ? 82 : 205)
        : Math.round(184 + Math.sin(x * 0.72) * 20 + Math.sin(y * 0.58) * 16);
      const offset = (y * resolution + x) * 4;
      data[offset] = value;
      data[offset + 1] = value;
      data[offset + 2] = value;
      data[offset + 3] = 255;
    }
  }
  return data;
}

export function taperedPartPivotTransform(part: DeterministicModelPart) {
  const { size, position, rotation } = modelPartTransform(part);
  const topPivot = part.几何 === "top_pivot_tapered_wood_leg";
  return {
    pivot: [
      position[0],
      position[1] + (topPivot ? size[1] / 2 : -size[1] / 2),
      position[2],
    ] as [number, number, number],
    childCenter: [0, topPivot ? -size[1] / 2 : size[1] / 2, 0] as [number, number, number],
    rotation,
    size,
  };
}
