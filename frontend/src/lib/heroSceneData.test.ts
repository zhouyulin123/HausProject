import { describe, expect, it } from "vitest";
import type { FurnitureItem } from "@/types/furniture";
import {
  SPACES,
  STYLES,
  heroModelBaseY,
  heroProductMap,
  heroSceneFor,
} from "@/lib/heroSceneData";

function product(sku: string, anchor: "floor" | "ceiling" = "floor"): FurnitureItem {
  return {
    id: sku,
    sku,
    name: `商品 ${sku}`,
    category: "测试",
    room: "测试",
    style: "测试",
    material: "测试",
    priceRange: "¥1",
    sizeSuggestion: "测试",
    matchScore: 90,
    reason: "测试",
    alternative: "测试",
    gradient: "",
    modelSpecJson: {
      安装参数: { 锚点: anchor },
      确定性建模规则: {
        规则状态: "ready",
        包围尺寸_mm: { 宽: 600, 高: 1800, 深: 600 },
      },
    },
  } as FurnitureItem;
}

describe("首页真实商品模型场景", () => {
  it("三个空间与四种风格都只引用真实商品 SKU", () => {
    for (const space of SPACES) {
      for (const style of STYLES) {
        const scene = heroSceneFor(space, style);
        expect(scene.items.length).toBeGreaterThanOrEqual(4);
        expect(scene.items.every((item) => !item.sku.startsWith("DEMO-"))).toBe(true);
      }
    }
  });

  it("切换风格会替换场景中的真实家具款式", () => {
    for (const space of SPACES) {
      const variants = STYLES.map((style) =>
        heroSceneFor(space, style).items.map((item) => item.sku).join("|"),
      );
      expect(new Set(variants).size).toBe(STYLES.length);
    }
  });

  it("只把存在 ready 确定性规则的商品交给首页场景", () => {
    const scene = heroSceneFor("客厅", "奶油风");
    const catalog = scene.items.map((item) => product(item.sku));
    const resolved = heroProductMap(scene, catalog);

    expect(Object.keys(resolved)).toHaveLength(scene.items.length);
    expect(Object.values(resolved).every(Boolean)).toBe(true);
    catalog[0].modelSpecJson!.确定性建模规则 = { 规则状态: "pending" };
    expect(heroProductMap(scene, catalog)[scene.items[0].instanceId]).toBeUndefined();
  });

  it("落地模型从地面起算，吊装模型按规则总高贴到天花", () => {
    expect(heroModelBaseY(product("FLOOR"), 2.8)).toBe(0);
    expect(heroModelBaseY(product("CEILING", "ceiling"), 2.8)).toBeCloseTo(1);
  });
});
