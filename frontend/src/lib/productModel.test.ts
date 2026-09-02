import { describe, expect, it } from "vitest";
import {
  getProductAssetState,
  getProductModelAsset,
  markInstanceGlbLoadFailed,
  millimetersToMeters,
  productAssetLabel,
} from "./productModel";

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
        assetMode: "approved_glb",
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
        modelStatus: "pending_review",
        modelDimensionsMm: { width: 2400, height: 850, depth: 1050 },
      }),
    ).toBeNull();
  });

  it("不从旧 modelStatus 自行宣称审核通过的真实 GLB", () => {
    expect(
      getProductAssetState({
        modelUrl: "/models/demo/sofa.glb",
        modelStatus: "ready",
        modelDimensionsMm: { width: 2400, height: 850, depth: 1050 },
      }),
    ).toEqual({
      assetMode: "parametric",
      fallbackReason: "asset_contract_missing",
      model: null,
    });
  });

  it("只把加载失败记录到对应实例且明确显示降级体块", () => {
    const current = {
      "sofa-main": {
        assetMode: "approved_glb" as const,
        fallbackReason: null,
      },
      "table-main": {
        assetMode: "parametric" as const,
        fallbackReason: "glb_unavailable" as const,
      },
    };

    const updated = markInstanceGlbLoadFailed(current, "sofa-main");

    expect(updated).not.toBe(current);
    expect(updated["sofa-main"]).toEqual({
      assetMode: "fallback",
      fallbackReason: "glb_load_failed",
    });
    expect(updated["table-main"]).toBe(current["table-main"]);
    expect(productAssetLabel(updated["sofa-main"])).toBe(
      "GLB 加载失败，已使用参数化体块",
    );
    expect(productAssetLabel(updated["sofa-main"])).not.toContain("真实模型");
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
