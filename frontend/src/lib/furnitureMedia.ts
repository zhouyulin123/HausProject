import type { FurnitureItem } from "@/types/furniture";

export type FurnitureMediaMode = "image" | "3d";

export function furnitureMediaModes(item: FurnitureItem): FurnitureMediaMode[] {
  const modes: FurnitureMediaMode[] = [];
  if (item.imageUrl) modes.push("image");
  if (item.modelSpecJson || item.modelUrl) modes.push("3d");
  return modes.length ? modes : ["image"];
}

export function initialFurnitureViewMode(item: FurnitureItem): FurnitureMediaMode {
  return furnitureMediaModes(item)[0];
}

function isReadyDeterministic(item: FurnitureItem): boolean {
  const rule = item.modelSpecJson?.确定性建模规则;
  return Boolean(
    rule
    && typeof rule === "object"
    && (rule as Record<string, unknown>).规则状态 === "ready",
  );
}

export function featuredFurniture(items: FurnitureItem[], limit = 5): FurnitureItem[] {
  return items
    .filter((item) => item.modelSpecJson || item.modelUrl)
    .sort((left, right) => Number(isReadyDeterministic(right)) - Number(isReadyDeterministic(left)))
    .slice(0, limit);
}
