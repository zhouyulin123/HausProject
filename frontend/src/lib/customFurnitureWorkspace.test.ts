import { describe, expect, it } from "vitest";
import {
  createCustomFurnitureDraft,
  customFurnitureFocusField,
  parseCustomFurniturePreview,
  quotePreviewDisplay,
} from "./customFurnitureWorkspace";

describe("自定义家具工作台映射", () => {
  it("按家具族生成完整且互不混用的结构化默认值", () => {
    const cabinet = createCustomFurnitureDraft("cabinet");
    const table = createCustomFurnitureDraft("table");

    expect(cabinet).toMatchObject({
      family: "cabinet",
      purpose: "wardrobe",
      dimensions: { width_mm: 1800, height_mm: 2400, depth_mm: 600 },
      structure: { door_style: "hinged", panel_thickness_mm: 18 },
    });
    expect(table).toMatchObject({
      family: "table",
      purpose: "dining_table",
      dimensions: { width_mm: 1600, height_mm: 750, depth_mm: 800 },
      structure: { top_shape: "rectangle", base_style: "four_leg", support_count: 4 },
    });
    expect(table.structure).not.toHaveProperty("door_style");
  });

  it("只按服务端 pending question 字段定位控件，不解析对话文本", () => {
    expect(
      customFurnitureFocusField([
        {
          field: "custom_furniture_spec.dimensions",
          prompt: "请提供宽、高、深三个毫米尺寸。",
          reason: "完整毫米尺寸是几何生成和报价复算的必要输入",
        },
      ]),
    ).toBe("dimensions");
    expect(customFurnitureFocusField([])).toBeNull();
  });

  it("仅接受包含确定性模型规则的服务端预览结果", () => {
    const result = {
      status: "preview_ready",
      spec: createCustomFurnitureDraft("cabinet"),
      model_spec: {
        家具类型: "定制柜体",
        确定性建模规则: {
          规则版本: "1.0.0",
          规则状态: "ready",
          模型ID: "CUSTOM-CABINET-001",
          生成器: "cabinet_v2",
          包围尺寸_mm: { 宽: 1800, 高: 2400, 深: 600 },
          外观规则: {},
          材质槽: [],
          部件: [],
        },
      },
      quote_preview: {
        status: "estimated",
        reason_code: null,
        rule_id: 3,
        project_name: "定制衣柜",
        material_grade: "E0 颗粒板",
        pricing_unit: "㎡",
        unit_price: 680,
        quantity: "4.320",
        estimated_amount: "2937.60",
        currency: "CNY",
        description: null,
      },
      warnings: ["投产前仍需工程复核。"],
    };

    expect(parseCustomFurniturePreview(result)?.model_spec.家具类型).toBe("定制柜体");
    expect(parseCustomFurniturePreview({ ...result, model_spec: {} })).toBeNull();
    expect(quotePreviewDisplay(result.quote_preview)).toMatchObject({
      amount: "¥2,937.60",
      state: "确定性估算",
    });
  });

  it("缺少唯一报价规则时不显示金额", () => {
    expect(
      quotePreviewDisplay({
        status: "needs_human",
        reason_code: "quote_rule_missing",
        rule_id: null,
        project_name: "定制餐桌",
        material_grade: "实木（橡木）",
        pricing_unit: null,
        unit_price: null,
        quantity: null,
        estimated_amount: null,
        currency: "CNY",
        description: null,
      }),
    ).toEqual({ amount: null, state: "待人工报价", reason: "未找到唯一可复算的报价规则" });
  });
});
