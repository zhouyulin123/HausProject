import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/designApi";
import OpenGeometryPanel, {
  AgentCheckpointRefreshError,
  createOpenGeometryRestoreCoordinator,
  openGeometryErrorMessage,
  previousOpenGeometryVersion,
  restoreOpenGeometryAndRefresh,
} from "./OpenGeometryPanel";
import type { OpenGeometryState } from "@/types/openGeometry";
import type { DesignAgentStateResponse } from "@/api/designApi";
import type { DesignScene } from "@/types/scene";


const emptyState: OpenGeometryState = {
  task_id: 42,
  current_version: 0,
  current: null,
  history: [],
};

const authoritativeScene = {
  id: 9,
  plan_version_id: 17,
  current_version: 3,
  scene: {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: {
      id: "room-1",
      name: "客厅",
      floorPolygon: [
        { x: 1, z: 2 },
        { x: 7, z: 2 },
        { x: 7, z: 6 },
        { x: 1, z: 6 },
      ],
      ceilingHeight: 2.8,
      wallThickness: 0.12,
    },
    openings: [],
    items: [],
  },
  validation: { valid: true, errors: [], warnings: [] },
  source: "manual",
} satisfies DesignScene;

describe("开放几何家具面板", () => {
  it("首次进入只提示通过左侧对话创建且撤销不可用", () => {
    const html = renderToStaticMarkup(
      <OpenGeometryPanel taskId={42} state={emptyState} onCheckpointRefresh={vi.fn()} />,
    );
    expect(html).toContain("对话式自由造型");
    expect(html).toContain("左侧对话");
    expect(html).toContain("撤销开放几何修改");
    expect(html).not.toContain("textarea");
    expect(html).not.toContain("生成并校验");
    expect(html).not.toContain("加宽 10%");
  });

  it("没有权威服务端场景时明确阻断加入房间", () => {
    const state = {
      ...emptyState,
      current_version: 1,
      current: {
        version: 1,
        source: "llm",
        instruction: "创建椅子",
        design: {
          schema_version: "furniture-open-geometry/1.0",
          name: "椅子",
          description: "",
          scale: [1, 1, 1],
          materials: [],
          parts: [],
        },
        model_spec: { 家具类型: "开放几何家具" },
      },
    } as OpenGeometryState;
    const html = renderToStaticMarkup(
      <OpenGeometryPanel taskId={42} state={state} onCheckpointRefresh={vi.fn()} />,
    );

    expect(html).toContain('data-placement-ready="false"');
    expect(html).toContain("当前没有已恢复的服务端房间场景");
  });

  it("已有版本展示稳定部件数和材质数，且不再展示旁路 patch 快捷入口", () => {
    const state: OpenGeometryState = {
      ...emptyState,
      current_version: 1,
      current: {
        version: 1,
        source: "llm",
        instruction: "创建弧形椅",
        design: {
          schema_version: "furniture-open-geometry/1.0",
          name: "弧形椅",
          description: "",
          scale: [1, 1, 1],
          materials: [{ id: "frame", name: "框架", base_color: "#334433", roughness: 0.4, metallic: 0.7 }],
          parts: [{ id: "arc", name: "弧形主体", material_id: "frame" }],
        },
        model_spec: { 家具类型: "开放几何家具" },
      },
      history: [],
    };
    const html = renderToStaticMarkup(
      <OpenGeometryPanel
        taskId={42}
        state={state}
        sceneReference={{ scene_id: 9, version: 3 }}
        authoritativeScene={authoritativeScene}
        onCheckpointRefresh={vi.fn()}
        onSceneApplied={vi.fn()}
      />,
    );
    expect(html).toContain("弧形椅");
    expect(html).toContain("1 个稳定部件");
    expect(html).toContain("1 种材质");
    expect(html).toContain("加入当前房间");
    expect(html).toContain('data-placement-ready="true"');
    expect(html).toContain('value="4"');
    expect(html).not.toContain("加宽 10%");
  });

  it("结构化失败提示明确保留当前模型", () => {
    expect(openGeometryErrorMessage(new ApiError("failed", 422, {
      code: "invalid_patch",
      message: "局部修改无效",
    }))).toContain("当前模型保持不变");
  });

  it("网络结果未知时不声称模型一定未变化", () => {
    const message = openGeometryErrorMessage(new Error("connection reset"));

    expect(message).toContain("结果未确认");
    expect(message).not.toContain("模型未被替换");
  });

  it("撤销已提交但 checkpoint 读取失败时提示刷新，不误报模型未变化", async () => {
    await expect(restoreOpenGeometryAndRefresh({
      restore: async () => emptyState,
      refresh: async () => { throw new Error("network"); },
      onCheckpointRefresh: vi.fn(),
    })).rejects.toBeInstanceOf(AgentCheckpointRefreshError);

    expect(openGeometryErrorMessage(new AgentCheckpointRefreshError())).toContain("刷新页面");
  });

  it("撤销成功后读取并应用全局 Agent checkpoint", async () => {
    const restored = vi.fn(async () => ({ ...emptyState, current_version: 1 }));
    const checkpoint = { task_id: 42, state_version: 9 } as DesignAgentStateResponse;
    const refreshed = vi.fn(async () => checkpoint);
    const onCheckpointRefresh = vi.fn();

    await restoreOpenGeometryAndRefresh({
      restore: restored,
      refresh: refreshed,
      onCheckpointRefresh,
    });

    expect(restored).toHaveBeenCalledOnce();
    expect(refreshed).toHaveBeenCalledOnce();
    expect(onCheckpointRefresh).toHaveBeenCalledWith(checkpoint);
  });

  it("撤销版本冲突时仍先恢复权威 checkpoint 再提示冲突", async () => {
    const conflict = new ApiError("conflict", 409, {
      code: "version_conflict",
      message: "开放几何版本已变化",
    });
    const checkpoint = { task_id: 42, state_version: 10 } as DesignAgentStateResponse;
    const refreshed = vi.fn(async () => checkpoint);
    const onCheckpointRefresh = vi.fn();

    await expect(restoreOpenGeometryAndRefresh({
      restore: async () => { throw conflict; },
      refresh: refreshed,
      onCheckpointRefresh,
    })).rejects.toBe(conflict);

    expect(refreshed).toHaveBeenCalledOnce();
    expect(onCheckpointRefresh).toHaveBeenCalledWith(checkpoint);
  });

  it("撤销结果未知时读取权威 checkpoint 后仍保留原错误", async () => {
    const failure = new Error("connection reset");
    const checkpoint = { task_id: 42, state_version: 10 } as DesignAgentStateResponse;
    const refreshed = vi.fn(async () => checkpoint);
    const onCheckpointRefresh = vi.fn();

    await expect(restoreOpenGeometryAndRefresh({
      restore: async () => { throw failure; },
      refresh: refreshed,
      onCheckpointRefresh,
    })).rejects.toBe(failure);

    expect(refreshed).toHaveBeenCalledOnce();
    expect(onCheckpointRefresh).toHaveBeenCalledWith(checkpoint);
  });

  it("相同撤销在结果未知后复用原幂等键", async () => {
    const restore = vi.fn()
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce(emptyState);
    const coordinator = createOpenGeometryRestoreCoordinator({
      createMutationId: vi.fn().mockReturnValueOnce("restore-stable"),
      restore,
    });
    const request = { baseVersion: 2, targetVersion: 1 };

    await expect(coordinator.restore(request)).rejects.toThrow("connection reset");
    await expect(coordinator.restore(request)).resolves.toBe(emptyState);

    expect(restore).toHaveBeenNthCalledWith(1, {
      ...request,
      clientMutationId: "restore-stable",
    });
    expect(restore).toHaveBeenNthCalledWith(2, {
      ...request,
      clientMutationId: "restore-stable",
    });
  });

  it("撤销目标始终取当前历史的上一有效版本", () => {
    const v1 = { version: 1 } as OpenGeometryState["history"][number];
    const v2 = { version: 2 } as OpenGeometryState["history"][number];
    expect(previousOpenGeometryVersion({ ...emptyState, current_version: 2, history: [v1, v2] })?.version).toBe(1);
    expect(previousOpenGeometryVersion(emptyState)).toBeNull();
  });
});
