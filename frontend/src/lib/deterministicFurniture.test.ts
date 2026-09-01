import { describe, expect, it } from "vitest";
import type { Furniture3DSpec } from "@/types/furniture";
import {
  cushionVertexPosition,
  deterministicFurnitureRule,
  modelPartTransform,
  previewLighting,
  roundPartScale,
  structuralSurfacePixels,
  taperedPartPivotTransform,
  resolveFurnitureRenderer,
  upholsteryAppearance,
  woodAppearance,
  woodGrainAxis,
  woodJoineryMarkers,
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
      木材: {
        树种: "深色白蜡木",
        纹理周期_mm: 42,
        法线强度: 0.16,
        透明面漆: { 强度: 0.14, 粗糙度: 0.62 },
        榫卯节点: { 启用: true, 榫肩线宽_mm: 1.2, 距构件端部_mm: 18 },
      },
    },
  },
} as Furniture3DSpec;

const coffeeTableSpec = {
  家具类型: "茶几",
  确定性建模规则: {
    规则版本: "1.0.0",
    规则状态: "ready",
    模型ID: "HAUS-COFFEE-003",
    生成器: "coffee_table_v1",
    包围尺寸_mm: { 宽: 1200, 高: 360, 深: 600 },
    材质槽: [],
    部件: [],
    外观规则: {
      木材: {
        树种: "北美白橡木木蜡油",
        纹理周期_mm: 54,
        法线强度: 0.17,
        透明面漆: { 强度: 0.08, 粗糙度: 0.72 },
        榫卯节点: { 启用: true, 榫肩线宽_mm: 1, 距构件端部_mm: 16 },
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

  it("ready 的圆角茶几进入确定性桌类生成器", () => {
    expect(resolveFurnitureRenderer(coffeeTableSpec)).toEqual({
      kind: "deterministic",
      generator: "coffee_table_v1",
    });
  });

  it("接受完整家具库的结构族生成器", () => {
    const generators = [
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
    ] as const;

    for (const generator of generators) {
      const spec = structuredClone(coffeeTableSpec);
      spec.确定性建模规则!.生成器 = generator;
      expect(resolveFurnitureRenderer(spec)).toEqual({ kind: "deterministic", generator });
    }
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

  it("圆柱类部件保留 X/Z 轴尺寸比例", () => {
    expect(roundPartScale({
      部件ID: "ceiling_plate",
      几何: "cylinder",
      尺寸_mm: [420, 24, 140],
      位置_mm: [0, 1200, 0],
      旋转_deg: [0, 0, 0],
      材质槽: "metal",
    })).toEqual([1, 1, 1 / 3]);
  });

  it("结构纹理用 RGBA 灰度像素，避免藤编和网布偏红", () => {
    const pixels = structuralSurfacePixels(4, true);
    expect(pixels).toHaveLength(4 * 4 * 4);
    for (let index = 0; index < pixels.length; index += 4) {
      expect(pixels[index]).toBe(pixels[index + 1]);
      expect(pixels[index + 1]).toBe(pixels[index + 2]);
      expect(pixels[index + 3]).toBe(255);
    }
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

  it("没有软包或木材外观时明确拒绝专用材质转换", () => {
    const rule = structuredClone(deterministicFurnitureRule(coffeeTableSpec)!);
    delete rule.外观规则.木材;
    expect(() => upholsteryAppearance(rule)).toThrow("规则没有软包外观数据");
    expect(() => woodAppearance(rule)).toThrow("规则没有木材外观数据");
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
    expect(cushionVertexPosition(
      "rounded_box",
      [0.1, 0.2, 0.3],
      [1, 1, 1],
      appearance,
    )).toEqual([0.1, 0.2, 0.3]);
  });

  it("把木材工艺转换为米制渲染参数", () => {
    expect(woodAppearance(deterministicFurnitureRule(deterministicSpec)!)).toEqual({
      species: "深色白蜡木",
      grainPeriod: 0.042,
      normalStrength: 0.16,
      clearcoat: 0.14,
      clearcoatRoughness: 0.62,
      joineryEnabled: true,
      shoulderLineWidth: 0.0012,
      shoulderInset: 0.018,
    });
  });

  it("木纹沿每个构件的最长本地轴排列", () => {
    expect(woodGrainAxis({
      部件ID: "front_seat_rail",
      几何: "wood_rail",
      尺寸_mm: [656, 46, 32],
      位置_mm: [0, 317, 246.5],
      旋转_deg: [0, 0, 0],
      材质槽: "wood_frame",
    })).toBe("x");
    expect(woodGrainAxis({
      部件ID: "front_left_leg",
      几何: "tapered_wood_leg",
      尺寸_mm: [32, 549, 32],
      位置_mm: [-344, 274.5, 246.5],
      旋转_deg: [0, 0, 0],
      材质槽: "wood_frame",
    })).toBe("y");
  });

  it("榫肩线在横梁两端按冻结距离定位", () => {
    const appearance = woodAppearance(deterministicFurnitureRule(deterministicSpec)!);
    expect(woodJoineryMarkers({
      部件ID: "front_seat_rail",
      几何: "wood_rail",
      尺寸_mm: [656, 46, 32],
      位置_mm: [0, 317, 246.5],
      旋转_deg: [0, 0, 0],
      材质槽: "wood_frame",
    }, appearance)).toEqual([
      { axis: "x", offset: -0.31 },
      { axis: "x", offset: 0.31 },
    ]);
    expect(woodJoineryMarkers({
      部件ID: "seat",
      几何: "rounded_box",
      尺寸_mm: [400, 60, 420],
      位置_mm: [0, 455, 0],
      旋转_deg: [0, 0, 0],
      材质槽: "wood_frame",
    }, appearance)).toEqual([]);
  });

  it("三点灯光按模型半径缩放且降低环境平光", () => {
    expect(previewLighting(0.4)).toEqual({
      ambientIntensity: 0.22,
      hemisphereIntensity: 0.62,
      key: { position: [1.12, 1.68, 0.88], intensity: 1.75, color: "#FFF2DE" },
      fill: { position: [-0.96, 0.88, 1.2], intensity: 0.48, color: "#DDE8F2" },
      rim: { position: [0.32, 1.36, -1.12], intensity: 0.72, color: "#FFE2BF" },
    });
  });
});
