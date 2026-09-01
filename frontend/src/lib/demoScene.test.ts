import { describe, expect, it } from "vitest";
import type { FurnitureItem } from "@/types/furniture";
import { demoItemRenderY, findAffectedInstanceIds } from "./demoScene";

function furniture(anchor?: "floor" | "ceiling"): FurnitureItem {
  return {
    id: "1",
    name: "测试家具",
    category: "灯具",
    room: "卧室",
    style: "日式风",
    material: "",
    priceRange: "¥1",
    sizeSuggestion: "",
    matchScore: 90,
    reason: "",
    alternative: "",
    gradient: "",
    sku: "DG-002",
    modelSpecJson: {
      家具类型: "床头吊灯",
      安装参数: anchor ? { 锚点: anchor, 默认垂吊_mm: 600 } : undefined,
    },
  };
}

describe("Demo 3D 场景辅助逻辑", () => {
  it("吊装模型使用房间层高作为程序化模型锚点", () => {
    expect(demoItemRenderY(furniture("ceiling"), 2.8)).toBe(2.8);
  });

  it("未声明吊装的家具保持落地", () => {
    expect(demoItemRenderY(furniture(), 2.8)).toBe(0);
  });

  it("识别新增及被操作的实例供跨轮指代使用", () => {
    const before = ["sofa-main"];
    const after = ["sofa-main", "item-CY-001-1"];
    const operations = [
      {
        type: "add" as const,
        sku: "CY-001",
        position: { x: 0, z: 0 },
        rotationY: 0,
      },
    ];

    expect(findAffectedInstanceIds(before, after, operations)).toEqual([
      "item-CY-001-1",
    ]);
  });
});
