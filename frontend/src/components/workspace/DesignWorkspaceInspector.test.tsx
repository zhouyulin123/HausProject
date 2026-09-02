import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createDesignProject } from "@/lib/designProject";
import { emptyRequirement } from "@/types/requirement";
import type { FurnitureItem } from "@/types/furniture";
import DesignWorkspaceInspector from "./DesignWorkspaceInspector";

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
        onPlanMutation={vi.fn()}
      />,
    );

    expect(html).toContain("已选家具");
    expect(html).toContain('aria-label="替换云朵沙发"');
    expect(html).toContain('aria-label="移除云朵沙发"');
    expect(html).toContain('aria-label="加入弧形沙发"');
  });
});
