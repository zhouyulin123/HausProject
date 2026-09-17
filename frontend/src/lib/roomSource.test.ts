import { beforeEach, describe, expect, it } from "vitest";
import { createDesignProject, restoreDesignProjectSeed } from "./designProject";
import { emptyRequirement } from "@/types/requirement";
import type { RoomModel } from "@/types/roomModel";
import { migrateDesignProjectState, useDesignProjectStore } from "@/store/useDesignProjectStore";

const model: RoomModel = {
  schemaVersion: "1.0", rooms: [{ id: "living", name: "客厅", confidence: 0.8,
    floorPolygon: [{ x: 0, z: 0 }, { x: 1, z: 0 }, { x: 1, z: 1 }] }],
  walls: [], doors: [], windows: [], fixedObstacles: [], existingFurniture: [],
  scale: { source: "vl", confidence: 0.8 }, confidence: 0.8,
  requiresConfirmation: [], analysisNotes: [], suggestions: [],
};
const source = { image_id: 8, image_url: "/uploads/8-plan.png", file_name: "户型.png" };

describe("空间模型与原图恢复", () => {
  beforeEach(() => useDesignProjectStore.setState({ projects: {}, currentProjectId: null }));

  it("浏览器缓存丢失时从同一个服务端快照恢复模型与原图", () => {
    const seed = restoreDesignProjectSeed({ confirmedRequirement: {}, facts: {}, roomModel: model, roomSource: source });
    const project = createDesignProject("room_reconstruction", seed, { id: 42 });
    expect(project.roomSource).toEqual(source);
    expect(project.roomModel).toEqual(model);
    expect(project.roomSource).not.toBe(source);
  });

  it("新上传整体替换空间上下文，不保留上一张图片的来源", () => {
    const store = useDesignProjectStore.getState();
    store.registerProject(42, "room_reconstruction", { requirement: emptyRequirement, roomModel: model });
    store.setRoomContext(42, { roomModel: model, roomSource: source });
    expect(useDesignProjectStore.getState().projects[42].roomSource).toEqual(source);
    store.setRoomModel(42, model);
    expect(useDesignProjectStore.getState().projects[42].roomSource).toBeNull();
    store.setRoomContext(42, { roomModel: null, roomSource: source });
    expect(useDesignProjectStore.getState().projects[42].roomSource).toBeNull();
  });

  it("旧缓存迁移补齐空来源，不猜测图片地址", () => {
    const project = createDesignProject("room_reconstruction", { requirement: emptyRequirement, roomModel: model }, { id: 42 });
    const { roomSource: _source, ...legacy } = project;
    const migrated = migrateDesignProjectState({ projects: { 42: legacy }, currentProjectId: 42 }, 5);
    expect(migrated.projects[42].roomSource).toBeNull();
  });

  it("上传后迟到的旧 checkpoint 不得清空或回退原图与模型", () => {
    const store = useDesignProjectStore.getState();
    store.registerProject(42, "room_reconstruction", { requirement: emptyRequirement, roomModel: model, roomSource: source });
    const base = {
      stateVersion: 0, status: "draft" as const, activeMode: "room_reconstruction" as const,
      pendingQuestions: [], sceneRef: null, exitReason: null,
    };
    for (const roomContext of [
      { roomModel: null, roomSource: null },
      { roomModel: model, roomSource: { ...source, image_id: 7 } },
    ]) {
      store.applyAgentState(42, { ...base, roomContext });
      expect(useDesignProjectStore.getState().projects[42].roomSource).toEqual(source);
      expect(useDesignProjectStore.getState().projects[42].roomModel).toEqual(model);
    }
    store.applyAgentState(42, { ...base, stateVersion: 1,
      roomContext: { roomModel: model, roomSource: { ...source, image_id: 9 } } });
    expect(useDesignProjectStore.getState().projects[42].roomSource?.image_id).toBe(9);
    store.applyAgentState(42, { ...base, roomContext: { roomModel: model, roomSource: source } });
    expect(useDesignProjectStore.getState().projects[42].roomSource?.image_id).toBe(9);
  });
});
