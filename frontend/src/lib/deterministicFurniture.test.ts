import { describe, expect, it } from "vitest";
import type { Furniture3DSpec } from "@/types/furniture";
import {
  modelPartTransform,
  resolveFurnitureRenderer,
} from "@/lib/deterministicFurniture";

const deterministicSpec = {
  家具类型: "单人椅",
  确定性建模规则: {
    规则版本: "1.0.0",
    规则状态: "ready",
    模型ID: "HAUS-CHAIR-001",
    生成器: "lounge_chair_v1",
    包围尺寸_mm: { 宽: 720, 高: 790, 深: 780 },
    材质槽: [],
    部件: [],
  },
} as Furniture3DSpec;

describe("确定性家具模型分发", () => {
  it("ready 的单人椅规则优先于旧 sofa 生成器", () => {
    expect(resolveFurnitureRenderer(deterministicSpec)).toEqual({
      kind: "deterministic",
      generator: "lounge_chair_v1",
    });
  });

  it("没有确定性规则时继续使用旧程序化模型", () => {
    expect(resolveFurnitureRenderer({ 家具类型: "单人椅" })).toEqual({
      kind: "legacy",
      generator: "sofa",
    });
  });

  it("把毫米和角度转换成 Three.js 变换", () => {
    expect(
      modelPartTransform({
        部件ID: "rear_left_leg",
        几何: "tapered_wood_leg",
        尺寸_mm: [32, 340, 32],
        位置_mm: [-344, 170, -374],
        旋转_deg: [-8, 0, 0],
        材质槽: "wood_frame",
      }),
    ).toEqual({
      size: [0.032, 0.34, 0.032],
      position: [-0.344, 0.17, -0.374],
      rotation: [-8 * Math.PI / 180, 0, 0],
    });
  });
});
