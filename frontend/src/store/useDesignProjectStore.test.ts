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
    useDesignProjectStore.getState().setMessages(999, []);
    useDesignProjectStore.getState().toggleFurniture(999, "f-1");

    expect(useDesignProjectStore.getState().projects).toEqual({});
  });

  it("用服务端 checkpoint 恢复项目状态和待确认问题", () => {
    useDesignProjectStore.getState().registerProject(42, "room_reconstruction", {
      requirement: emptyRequirement,
      roomModel: null,
    });

    useDesignProjectStore.getState().applyAgentState(42, {
      stateVersion: 7,
      status: "waiting_user",
      pendingQuestions: [
        { field: "room.width", prompt: "客厅实际宽度是多少？", reason: "空间尺度置信度不足" },
      ],
      sceneRef: { scene_id: 12, version: 4 },
      exitReason: "missing_facts",
    });

    expect(useDesignProjectStore.getState().projects[42]).toMatchObject({
      status: "waiting_user",
      stateVersion: 7,
      sceneRef: { scene_id: 12, version: 4 },
      exitReason: "missing_facts",
    });
    expect(
      useDesignProjectStore.getState().projects[42]?.pendingQuestions[0]?.prompt,
    ).toBe("客厅实际宽度是多少？");
  });
});
