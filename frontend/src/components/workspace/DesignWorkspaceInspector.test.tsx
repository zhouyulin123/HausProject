import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createDesignProject } from "@/lib/designProject";
import { emptyRequirement } from "@/types/requirement";
import type { FurnitureItem } from "@/types/furniture";
import DesignWorkspaceInspector, {
  commitFurnitureReplacement,
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
];

describe("工作台家具替换入口", () => {
  it("仅在本地替换成功且有真实方案版本时构建一条 replace 事件", () => {
    const rejected = vi.fn(() => false);
    expect(commitFurnitureReplacement({
      replaceSelection: rejected,
      clientEventId: "feedback-42-replace-rejected",
      planVersionId: 8,
      sourceSku: "SOFA-OLD",
      targetSku: "SOFA-NEW",
      roomId: null,
    })).toEqual({ completed: false, event: null });
    expect(rejected).toHaveBeenCalledOnce();

    const localOnly = vi.fn(() => true);
    expect(commitFurnitureReplacement({
      replaceSelection: localOnly,
      clientEventId: "feedback-42-replace-local",
      planVersionId: null,
      sourceSku: "SOFA-OLD",
      targetSku: "SOFA-NEW",
      roomId: null,
    })).toEqual({ completed: true, event: null });

    expect(commitFurnitureReplacement({
      replaceSelection: () => true,
      clientEventId: "feedback-42-replace-sent",
      planVersionId: 8,
      sourceSku: "SOFA-OLD",
      targetSku: "SOFA-NEW",
      roomId: "living-room",
    })).toMatchObject({
      completed: true,
      event: {
        action_type: "replace",
        source_sku: "SOFA-OLD",
        target_sku: "SOFA-NEW",
      },
    });
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
        budget={0}
        planVersionId={8}
        onFeedbackEvent={vi.fn()}
      />,
    );

    expect(html).toContain("已选家具");
    expect(html).toContain('aria-label="替换云朵沙发"');
    expect(html).toContain('aria-label="移除云朵沙发"');
    expect(html).toContain('aria-label="加入弧形沙发"');
  });
});
