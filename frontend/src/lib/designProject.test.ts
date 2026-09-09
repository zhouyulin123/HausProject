import { describe, expect, it } from "vitest";
import { mockFurniture } from "@/data/mockFurniture";
import { emptyRequirement } from "@/types/requirement";
import {
  DESIGN_ENTRY_MODES,
  buildWorkspacePlan,
  createDesignProject,
  designWorkspacePath,
  restoreDesignProjectSeed,
} from "./designProject";

describe("设计项目契约", () => {
  it("提供三个稳定且互斥的用户入口", () => {
    expect(DESIGN_ENTRY_MODES.map((entry) => entry.id)).toEqual([
      "catalog_design",
      "custom_furniture",
      "room_reconstruction",
    ]);
  });

  it("创建项目时保存意图和需求快照", () => {
    const requirement = {
      ...emptyRequirement,
      rooms: ["客厅"],
      budgetRange: "8-15 万",
    };
    const project = createDesignProject(
      "catalog_design",
      { requirement, roomModel: null },
      { id: 42, now: "2026-09-01T10:00:00.000Z" },
    );

    requirement.rooms.push("卧室");

    expect(project.id).toBe(42);
    expect(project.mode).toBe("catalog_design");
    expect(project.requirement.rooms).toEqual(["客厅"]);
    expect(project.messages[0]?.content).toContain("现有家具");
    expect(designWorkspacePath(project.id)).toBe(
      "/design/42/workspace",
    );
  });

  it("根据项目家具选择生成可交互工作台草案", () => {
    const selected = mockFurniture.slice(0, 2);
    const project = createDesignProject(
      "catalog_design",
      { requirement: emptyRequirement, roomModel: null },
      { id: 42, now: "2026-09-01T10:00:00.000Z" },
    );
    project.selectedFurnitureIds = selected.map((item) => item.id);

    const plan = buildWorkspacePlan(project, selected);

    expect(plan.id).toBe("workspace-42");
    expect(plan.furnitureSuggestions.map((item) => item.id)).toEqual(
      selected.map((item) => item.id),
    );
    expect(plan.tags).toContain("商品搭配");
  });

  it("从服务端事实恢复丢失的本地项目骨架", () => {
    const seed = restoreDesignProjectSeed({
      confirmedRequirement: {
        rooms: "历史坏值",
        city: "上海",
        budgetRange: "8-15 万",
        hasPets: true,
        familySize: 3,
      },
      facts: { space_type: "客厅", style: "现代简约" },
      roomModel: null,
    });

    expect(seed.requirement).toMatchObject({
      rooms: ["客厅"],
      styles: ["现代简约"],
      city: "上海",
      budgetRange: "8-15 万",
      hasPets: true,
      familySize: 3,
    });
    expect(seed.requirement.colors).toEqual([]);
    expect(seed.roomModel).toBeNull();
  });
});
