import type { Furniture3DSpec } from "@/types/furniture";

export type FurnitureModelKind =
  | "sofa"
  | "coffeeTable"
  | "bed"
  | "diningTable"
  | "officeChair"
  | "chair"
  | "lamp"
  | "rug"
  | "curtain"
  | "nightstand"
  | "desk"
  | "bookshelf"
  | "fallback";

/** 先识别更具体的灯具类型，避免“床头吊灯”误命中床。 */
export function furnitureModelKind(type: string): FurnitureModelKind {
  if (type.includes("灯")) return "lamp";
  if (type.includes("沙发") || type.includes("单人椅") || type.includes("转角")) {
    return "sofa";
  }
  if (type.includes("茶几") || type.includes("套几")) return "coffeeTable";
  if (type.includes("床头柜")) return "nightstand";
  if (type.includes("床")) return "bed";
  if (type.includes("餐桌")) return "diningTable";
  if (type.includes("工学椅") || type.includes("人体工学")) return "officeChair";
  if (type.includes("餐椅")) return "chair";
  if (type.includes("地毯")) return "rug";
  if (type.includes("窗帘")) return "curtain";
  if (type.includes("书桌") || type.includes("桌")) return "desk";
  if (type.includes("书架") || type.includes("书柜")) return "bookshelf";
  return "fallback";
}

export function lampModelKind(
  spec: Furniture3DSpec,
): "floor" | "pendant" | "ring" {
  const explicitKind = spec.安装参数?.灯具模型;
  if (explicitKind) return explicitKind;
  const type = spec.家具类型 ?? "";
  if (type.includes("落地灯")) return "floor";
  if (type.includes("吊线")) return "pendant";
  if (type.includes("吊灯")) return "ring";
  return "floor";
}
