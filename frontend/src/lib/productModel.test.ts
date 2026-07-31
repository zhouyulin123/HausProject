import { describe, expect, it } from "vitest";
import { getProductModelAsset, millimetersToMeters } from "./productModel";

describe("商品 3D 模型资产", () => {
  it("把后台毫米尺寸转换为场景米制尺寸", () => {
    expect(
      millimetersToMeters({
        width: 2400,
        height: 850,
        depth: 1050,
      }),
    ).toEqual({ x: 2.4, y: 0.85, z: 1.05 });
  });

  it("只有 ready 且尺寸完整时才返回可加载模型", () => {
    expect(
      getProductModelAsset({
        modelUrl: "/models/demo/sofa.glb",
        modelStatus: "ready",
        modelDimensionsMm: { width: 2400, height: 850, depth: 1050 },
      }),
    ).toEqual({
      url: "/models/demo/sofa.glb",
      dimensions: { x: 2.4, y: 0.85, z: 1.05 },
    });
    expect(
      getProductModelAsset({
        modelUrl: "/models/demo/sofa.glb",
        modelStatus: "failed",
        modelDimensionsMm: { width: 2400, height: 850, depth: 1050 },
      }),
    ).toBeNull();
  });

  it("拒绝零值、负值和不完整尺寸", () => {
    expect(
      getProductModelAsset({
        modelUrl: "/models/demo/table.glb",
        modelStatus: "ready",
        modelDimensionsMm: { width: 0, height: 750, depth: 800 },
      }),
    ).toBeNull();
  });
});
