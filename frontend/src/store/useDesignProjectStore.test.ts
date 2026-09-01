import { beforeEach, describe, expect, it } from "vitest";
import { emptyRequirement } from "@/types/requirement";
import { useDesignProjectStore } from "./useDesignProjectStore";

describe("useDesignProjectStore", () => {
  beforeEach(() => {
    useDesignProjectStore.setState({ projects: {}, currentProjectId: null });
  });

  it("不同项目的对话和家具选择互不污染", () => {
    const firstId = useDesignProjectStore
      .getState()
      .registerProject(41, "catalog_design", {
        requirement: emptyRequirement,
        roomModel: null,
      });
    const secondId = useDesignProjectStore
      .getState()
      .registerProject(42, "custom_furniture", {
        requirement: emptyRequirement,
        roomModel: null,
      });

    useDesignProjectStore.getState().setMessages(firstId, [
      { id: "u-1", role: "user", content: "保留电视柜" },
    ]);
    useDesignProjectStore.getState().toggleFurniture(firstId, "f-1");

    expect(useDesignProjectStore.getState().projects[firstId]?.messages).toHaveLength(1);
    expect(
      useDesignProjectStore.getState().projects[firstId]?.selectedFurnitureIds,
    ).toEqual(["f-1"]);
    expect(useDesignProjectStore.getState().projects[secondId]?.messages).toHaveLength(1);
    expect(
      useDesignProjectStore.getState().projects[secondId]?.selectedFurnitureIds,
    ).toEqual([]);
  });

  it("更新不存在的项目时保持状态不变", () => {
    useDesignProjectStore.getState().setMessages("missing", []);
    useDesignProjectStore.getState().toggleFurniture("missing", "f-1");

    expect(useDesignProjectStore.getState().projects).toEqual({});
  });
});
