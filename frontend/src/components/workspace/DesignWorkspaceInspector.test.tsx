import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createDesignProject } from "@/lib/designProject";
import { emptyRequirement } from "@/types/requirement";
import type { FurnitureItem } from "@/types/furniture";
import type { DesignPlan } from "@/types/design";
import DesignWorkspaceInspector, {
  workspaceFactRows,
  workspaceQuotePresentation,
} from "./DesignWorkspaceInspector";

const catalog: FurnitureItem[] = [
  {
    id: "sofa-old",
    sku: "SOFA-OLD",
    name: "云朵沙发",
    category: "沙发",
    room: "客厅",
    style: "现代",
    material: "布艺",
    priceRange: "¥5,000",
    sizeSuggestion: "2200mm",
    matchScore: 90,
    reason: "",
    alternative: "",
    gradient: "bg-stone-700",
    dataOrigin: "verified",
  },
  {
    id: "sofa-new",
    sku: "SOFA-NEW",
    name: "弧形沙发",
    category: "沙发",
    room: "客厅",
    style: "现代",
    material: "皮革",
    priceRange: "¥6,000",
    sizeSuggestion: "2400mm",
    matchScore: 88,
    reason: "",
    alternative: "",
    gradient: "bg-stone-600",
    dataOrigin: "verified",
  },
  {
    id: "chair-draft",
    sku: "CHAIR-DRAFT",
    name: "草稿单椅",
    category: "单椅",
    room: "客厅",
    style: "现代",
    material: "布艺",
    priceRange: "¥1,200",
    sizeSuggestion: "800mm",
    reason: "",
    alternative: "",
    gradient: "bg-stone-500",
    dataOrigin: "merchant",
    catalogEligibility: {
      eligible: false,
      reasonCodes: ["verification_required"],
    },
  },
];

const plan = {
  id: "plan-1",
  name: "正式方案",
  style: "现代",
  coverGradient: "",
  budget: 999999,
  tags: [],
  suitableFor: [],
  description: "",
  layoutSuggestions: [],
  furnitureSuggestions: [],
  colorPalette: [],
  materials: [],
  lightingSuggestions: [],
  budgetBreakdown: [],
  aiTips: [],
} satisfies DesignPlan;

describe("工作台家具替换入口", () => {
  it("只展示白名单 Agent 事实并标明证据状态", () => {
    const project = createDesignProject(
      "room_reconstruction",
      { requirement: emptyRequirement, roomModel: null },
      { id: 42 },
    );
    project.facts = {
      space_type: "客厅",
      room_width_m: 4.2,
      private_note: "不应展示",
    };
    project.factEvidence = {
      space_type: { confidence: 0.91, accepted: true },
      room_width_m: { confidence: 0.42, confirmation_required: true },
    };

    expect(workspaceFactRows(project)).toEqual([
      expect.objectContaining({ key: "space_type", value: "客厅", confidence: 91 }),
      expect.objectContaining({
        key: "room_width_m",
        value: "4.2 m",
        confirmationRequired: true,
      }),
    ]);
  });

  it("为已选家具提供明确替换动作，并保留目录加入/移除语义", () => {
    const project = createDesignProject(
      "catalog_design",
      { requirement: emptyRequirement, roomModel: null },
      { id: 42, now: "2026-09-02T00:00:00.000Z" },
    );
    project.selectedFurnitureIds = ["sofa-old"];

    const html = renderToStaticMarkup(
      <DesignWorkspaceInspector
        project={project}
        catalog={catalog}
        catalogLoading={false}
        plan={plan}
        onPlanMutation={vi.fn()}
      />,
    );

    expect(html).toContain("已选家具");
    expect(html).toContain('aria-label="替换云朵沙发"');
    expect(html).toContain('aria-label="移除云朵沙发"');
    expect(html).toContain('aria-label="加入弧形沙发"');
    expect(html).toContain('aria-label="草稿单椅商业信息待核验"');
    expect(html).toContain("商业信息待核验，暂不可用于方案");
  });

  it("只接受服务端确定性报价，不解析商品展示价格或方案预算", () => {
    expect(workspaceQuotePresentation(plan)).toEqual({
      available: false,
      total: null,
      furnitureTotal: null,
      customTotal: null,
    });
    expect(
      workspaceQuotePresentation({
        ...plan,
        shopQuote: { furnitureTotal: 8800, customTotal: 1200, total: 10000 },
      }),
    ).toEqual({
      available: true,
      total: 10000,
      furnitureTotal: 8800,
      customTotal: 1200,
    });
  });
});
