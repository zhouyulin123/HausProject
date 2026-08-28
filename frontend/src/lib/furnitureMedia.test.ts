import { describe, expect, it } from "vitest";
import type { FurnitureItem } from "@/types/furniture";
import {
  featuredFurniture,
  furnitureMediaModes,
  initialFurnitureViewMode,
} from "@/lib/furnitureMedia";

function item(overrides: Partial<FurnitureItem>): FurnitureItem {
  return {
    id: "1",
    name: "测试家具",
    category: "茶几",
    room: "客厅",
    style: "原木风",
    material: "白橡木",
    priceRange: "¥1,600",
    sizeSuggestion: "1200 × 600 × 360mm",
    matchScore: 92,
    reason: "真实参数建模",
    alternative: "同系列",
    gradient: "bg-stone-200",
    ...overrides,
  };
}

describe("家具媒体策略", () => {
  it("无图片但有模型时直接展示 3D，不出现空白图片页", () => {
    const furniture = item({ modelSpecJson: { 家具名称: "测试家具" } });
    expect(furnitureMediaModes(furniture)).toEqual(["3d"]);
    expect(initialFurnitureViewMode(furniture)).toBe("3d");
  });

  it("图片和模型都存在时允许轮换两种媒体", () => {
    const furniture = item({
      imageUrl: "/products/table.webp",
      modelSpecJson: { 家具名称: "测试家具" },
    });
    expect(furnitureMediaModes(furniture)).toEqual(["image", "3d"]);
    expect(initialFurnitureViewMode(furniture)).toBe("image");
  });

  it("首页优先选择 ready 确定性模型并限制轮播数量", () => {
    const legacy = item({ id: "legacy", modelSpecJson: { 家具名称: "旧模型" } });
    const ready = Array.from({ length: 7 }, (_, index) => item({
      id: `ready-${index}`,
      modelSpecJson: {
        家具名称: `确定性模型${index}`,
        确定性建模规则: { 规则状态: "ready" },
      } as FurnitureItem["modelSpecJson"],
    }));

    expect(featuredFurniture([legacy, ...ready]).map((entry) => entry.id)).toEqual([
      "ready-0", "ready-1", "ready-2", "ready-3", "ready-4",
    ]);
  });
});
