import { describe, expect, it } from "vitest";
import type { Furniture3DSpec } from "@/types/furniture";
import {
  cushionVertexPosition,
  deterministicFurnitureRule,
  modelPartTransform,
  taperedPartPivotTransform,
  resolveFurnitureRenderer,
  upholsteryAppearance,
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
    外观规则: {
      软包: {
        滚边: { 启用: true, 直径_mm: 7 },
        缝线: { 启用: true, 线径_mm: 1.4, 内缩_mm: 10 },
        绒面: { 方向性: true, 法线强度: 0.2, 纹理周期_mm: 3 },
        坐垫形变: { 前缘压缩: 0.04, 中心隆起_mm: 10 },
        靠背曲面: { 横向弧度半径_mm: 900 },
      },
    },
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

  it("锥形木构件围绕底部中心旋转，连接点不会漂移", () => {
    expect(
      taperedPartPivotTransform({
        部件ID: "rear_left_leg",
        几何: "tapered_wood_leg",
        尺寸_mm: [32, 340, 32],
        位置_mm: [-344, 170, -374],
        旋转_deg: [8, 0, 0],
        材质槽: "wood_frame",
      }),
    ).toEqual({
      pivot: [-0.344, 0, -0.374],
      childCenter: [0, 0.17, 0],
      rotation: [8 * Math.PI / 180, 0, 0],
      size: [0.032, 0.34, 0.032],
    });
  });

  it("把软包工艺统一转换为米制渲染参数", () => {
    expect(upholsteryAppearance(deterministicFurnitureRule(deterministicSpec)!)).toEqual({
      pipingEnabled: true,
      pipingRadius: 0.0035,
      seamEnabled: true,
      seamRadius: 0.0007,
      seamInset: 0.01,
      normalStrength: 0.2,
      fabricPeriod: 0.003,
      directionalNap: true,
      frontCompression: 0.04,
      crown: 0.01,
      backCurveRadius: 0.9,
    });
  });

  it("靠背中心按 900mm 横向半径向前形成微弧", () => {
    const appearance = upholsteryAppearance(deterministicFurnitureRule(deterministicSpec)!);
    const center = cushionVertexPosition(
      "curved_cushion",
      [0, 0, 0.0425],
      [0.57, 0.36, 0.085],
      appearance,
    );
    const edge = cushionVertexPosition(
      "curved_cushion",
      [0.285, 0, 0.0425],
      [0.57, 0.36, 0.085],
      appearance,
    );

    expect(center[2]).toBeGreaterThan(edge[2]);
    expect(center[2] - edge[2]).toBeCloseTo(0.0463, 3);
  });

  it("坐垫前缘压缩并保留中心隆起", () => {
    const appearance = upholsteryAppearance(deterministicFurnitureRule(deterministicSpec)!);
    const frontTop = cushionVertexPosition(
      "rounded_cushion",
      [0, 0.045, 0.2625],
      [0.57, 0.09, 0.525],
      appearance,
    );
    const centerTop = cushionVertexPosition(
      "rounded_cushion",
      [0, 0.045, 0],
      [0.57, 0.09, 0.525],
      appearance,
    );

    expect(frontTop[1]).toBeCloseTo(0.0432, 4);
    expect(centerTop[1]).toBeCloseTo(0.055, 4);
  });
});
