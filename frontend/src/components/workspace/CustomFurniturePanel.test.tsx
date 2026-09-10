import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/designApi";
import CustomFurniturePanel, {
  StructuredFurnitureCheckpointRefreshError,
  submitStructuredFurnitureTurnWithConflictRecovery,
} from "./CustomFurniturePanel";
import type { CustomFurniturePreviewResult } from "@/types/customFurniture";

function previewResult(
  quote: CustomFurniturePreviewResult["quote_preview"],
): CustomFurniturePreviewResult {
  return {
    status: quote.status === "estimated" ? "preview_ready" : "needs_human",
    spec: {
      family: "table",
      name: "六人位定制餐桌",
      purpose: "dining_table",
      material: "实木（橡木）",
      dimensions: { width_mm: 1600, height_mm: 750, depth_mm: 800 },
      structure: {
        top_shape: "rectangle",
        base_style: "four_leg",
        support_count: 4,
        seat_count: 6,
        top_thickness_mm: 36,
        edge_radius_mm: 12,
      },
    },
    model_spec: {
      家具类型: "定制餐桌",
      确定性建模规则: {
        规则版本: "1.0.0",
        规则状态: "ready",
        模型ID: "CUSTOM-TABLE-001",
        生成器: "table_v2",
        包围尺寸_mm: { 宽: 1600, 高: 750, 深: 800 },
        外观规则: {},
        材质槽: [],
        部件: [],
      },
    },
    quote_preview: quote,
    warnings: ["投产前仍需工程复核。"],
  };
}

const quoteBase = {
  rule_id: 12,
  project_name: "定制餐桌",
  material_grade: "实木（橡木）",
  pricing_unit: "件",
  unit_price: 6800,
  quantity: "1",
  currency: "CNY" as const,
  description: "按件估算",
};

describe("自定义家具结构化面板", () => {
  it("结构化 turn 冲突时只恢复 checkpoint，不自动重放语义请求", async () => {
    const conflict = new ApiError("conflict", 409, {
      code: "agent_state_conflict",
    });
    const submit = vi.fn(async () => { throw conflict; });
    const refresh = vi.fn(async () => undefined);

    await expect(submitStructuredFurnitureTurnWithConflictRecovery({
      submit,
      refresh,
    })).rejects.toBe(conflict);

    expect(submit).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("结构化 turn 冲突且 checkpoint 恢复失败时阻断继续提交", async () => {
    const conflict = new ApiError("conflict", 409, {
      code: "agent_state_conflict",
    });

    await expect(submitStructuredFurnitureTurnWithConflictRecovery({
      submit: async () => { throw conflict; },
      refresh: async () => { throw new Error("network"); },
    })).rejects.toBeInstanceOf(StructuredFurnitureCheckpointRefreshError);
  });

  it("显示家具族、毫米尺寸和服务端待确认提示", () => {
    const html = renderToStaticMarkup(
      <CustomFurniturePanel
        taskId={42}
        stateVersion={0}
        initialSpec={null}
        preview={null}
        approvalRequired={false}
        pendingQuestions={[
          {
            field: "custom_furniture_spec.dimensions",
            prompt: "请提供宽、高、深三个毫米尺寸。",
            reason: "完整毫米尺寸是几何生成和报价复算的必要输入",
          },
        ]}
        sceneReference={null}
        savedDraftReference={null}
        onDraftSaved={vi.fn()}
        onSceneApplied={vi.fn()}
        onAgentResponse={vi.fn()}
        onConversationTurn={vi.fn()}
      />,
    );

    expect(html).toContain("柜体");
    expect(html).toContain("桌类");
    expect(html).toContain("宽度（mm）");
    expect(html).toContain("请提供宽、高、深三个毫米尺寸。");
    expect(html).toContain("生成参数预览");
  });

  it("仅在服务端返回确定性报价时显示金额", () => {
    const preview = previewResult({
      ...quoteBase,
      status: "estimated",
      reason_code: null,
      estimated_amount: "6800.00",
    });
    const html = renderToStaticMarkup(
      <CustomFurniturePanel
        taskId={42}
        stateVersion={0}
        initialSpec={preview.spec}
        preview={preview}
        approvalRequired={false}
        pendingQuestions={[]}
        sceneReference={null}
        savedDraftReference={null}
        onDraftSaved={vi.fn()}
        onSceneApplied={vi.fn()}
        onAgentResponse={vi.fn()}
        onConversationTurn={vi.fn()}
      />,
    );

    expect(html).toContain("参数预览已就绪");
    expect(html).toContain("确定性估算");
    expect(html).toContain("6,800.00");
    expect(html).toContain("待工程复核");
  });

  it("缺少报价规则时不显示金额并标记人工确认", () => {
    const preview = previewResult({
      ...quoteBase,
      status: "needs_human",
      reason_code: "quote_rule_missing",
      rule_id: null,
      pricing_unit: null,
      unit_price: null,
      quantity: null,
      estimated_amount: null,
      description: null,
    });
    const html = renderToStaticMarkup(
      <CustomFurniturePanel
        taskId={42}
        stateVersion={0}
        initialSpec={preview.spec}
        preview={preview}
        approvalRequired
        pendingQuestions={[]}
        sceneReference={null}
        savedDraftReference={null}
        onDraftSaved={vi.fn()}
        onSceneApplied={vi.fn()}
        onAgentResponse={vi.fn()}
        onConversationTurn={vi.fn()}
      />,
    );

    expect(html).toContain("参数预览需人工确认");
    expect(html).toContain("待人工报价");
    expect(html).toContain("需要人工确认报价");
    expect(html).not.toContain("6,800.00");
  });

  it("仅允许把已确认保存且规格一致的草稿加入服务端房间", () => {
    const preview = previewResult({
      ...quoteBase,
      status: "estimated",
      reason_code: null,
      estimated_amount: "6800.00",
    });
    const html = renderToStaticMarkup(
      <CustomFurniturePanel
        taskId={42}
        stateVersion={2}
        initialSpec={preview.spec}
        preview={preview}
        approvalRequired={false}
        pendingQuestions={[]}
        sceneReference={{ scene_id: 9, version: 3 }}
        savedDraftReference={{
          clientMutationId: "draft-custom-001",
          specSignature: JSON.stringify(preview.spec),
        }}
        onDraftSaved={vi.fn()}
        onSceneApplied={vi.fn()}
        onAgentResponse={vi.fn()}
        onAgentStateConflict={vi.fn()}
        onConversationTurn={vi.fn()}
      />,
    );

    expect(html).toContain('data-placement-ready="true"');
    expect(html).toContain("参数化草稿体块");
    expect(html).toContain("不代表制造级资产或正式商品");
  });
});
