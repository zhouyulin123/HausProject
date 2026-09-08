import { beforeEach, describe, expect, it } from "vitest";
import { emptyRequirement } from "@/types/requirement";
import {
  migrateDesignProjectState,
  useDesignProjectStore,
} from "./useDesignProjectStore";
import { agentTurnSceneContext } from "@/lib/sceneEditingPolicy";

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

  it("原子替换已选家具，并拒绝无效或重复目标", () => {
    const projectId = useDesignProjectStore
      .getState()
      .registerProject(44, "catalog_design", {
        requirement: emptyRequirement,
        roomModel: null,
      });
    useDesignProjectStore.getState().setFurnitureSelection(projectId, ["sofa-old", "lamp"]);

    expect(
      useDesignProjectStore.getState().replaceFurniture(projectId, "sofa-old", "sofa-new"),
    ).toBe(true);
    expect(
      useDesignProjectStore.getState().projects[projectId]?.selectedFurnitureIds,
    ).toEqual(["sofa-new", "lamp"]);

    expect(
      useDesignProjectStore.getState().replaceFurniture(projectId, "missing", "table"),
    ).toBe(false);
    expect(
      useDesignProjectStore.getState().replaceFurniture(projectId, "sofa-new", "lamp"),
    ).toBe(false);
    expect(
      useDesignProjectStore.getState().replaceFurniture(projectId, "sofa-new", "sofa-new"),
    ).toBe(false);
    expect(
      useDesignProjectStore.getState().projects[projectId]?.selectedFurnitureIds,
    ).toEqual(["sofa-new", "lamp"]);
  });

  it("用服务端 checkpoint 恢复项目状态和待确认问题", () => {
    useDesignProjectStore.getState().registerProject(42, "room_reconstruction", {
      requirement: emptyRequirement,
      roomModel: null,
    });

    useDesignProjectStore.getState().applyAgentState(42, {
      stateVersion: 7,
      status: "waiting_user",
      activeMode: "room_reconstruction",
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

  it("完整保留服务端执行快照和工具事件", () => {
    useDesignProjectStore.getState().registerProject(46, "catalog_design", {
      requirement: emptyRequirement,
      roomModel: null,
    });

    useDesignProjectStore.getState().applyAgentState(46, {
      stateVersion: 8,
      status: "running",
      activeMode: "catalog_design",
      pendingQuestions: [],
      sceneRef: null,
      exitReason: "generation_queued",
      execution: {
        currentNode: "retrieve_catalog",
        stepCount: 4,
        retryCount: 1,
        maxSteps: 12,
        maxRetries: 2,
        hardErrors: [],
        costCny: 0.36,
        costReservedCny: 0.14,
        costLimitCny: 2,
        executionDeadlineAt: "2026-09-08T08:30:00Z",
        turnExecutionDeadlineAt: "2026-09-08T08:25:00Z",
        cancelRequestedAt: null,
        events: [
          {
            sequence: 3,
            type: "tool_completed",
            node: "retrieve_catalog",
            status: "completed",
            source: "catalog",
            summary: "已筛选 12 件可用商品",
            details: {},
            created_at: "2026-09-08T08:20:00Z",
          },
        ],
      },
    });

    expect(useDesignProjectStore.getState().projects[46]?.execution).toEqual({
      currentNode: "retrieve_catalog",
      stepCount: 4,
      retryCount: 1,
      maxSteps: 12,
      maxRetries: 2,
      hardErrors: [],
      costCny: 0.36,
      costReservedCny: 0.14,
      costLimitCny: 2,
      executionDeadlineAt: "2026-09-08T08:30:00Z",
      turnExecutionDeadlineAt: "2026-09-08T08:25:00Z",
      cancelRequestedAt: null,
      events: [
        expect.objectContaining({
          sequence: 3,
          type: "tool_completed",
          summary: "已筛选 12 件可用商品",
        }),
      ],
    });
  });

  it("场景加载 v1 后保存 v2，工作台与对话始终读取最新场景引用", () => {
    useDesignProjectStore.getState().registerProject(42, "catalog_design", {
      requirement: emptyRequirement,
      roomModel: null,
    });

    useDesignProjectStore.getState().setSceneReference(42, {
      scene_id: 9,
      version: 1,
    });
    useDesignProjectStore.getState().setSceneReference(42, {
      scene_id: 9,
      version: 2,
    });
    useDesignProjectStore.getState().applyAgentState(42, {
      stateVersion: 3,
      status: "completed",
      activeMode: "catalog_design",
      pendingQuestions: [],
      sceneRef: { scene_id: 9, version: 1 },
      exitReason: "goal_completed",
    });

    const latestReference = useDesignProjectStore.getState().projects[42]?.sceneRef;
    expect(latestReference).toEqual({
      scene_id: 9,
      version: 2,
    });
    expect(agentTurnSceneContext(
      latestReference?.scene_id,
      latestReference?.version,
    )).toEqual({ scene_id: 9, base_scene_version: 2 });
  });

  it("用加入接口返回的完整权威场景替换项目快照", () => {
    useDesignProjectStore.getState().registerProject(49, "custom_furniture", {
      requirement: emptyRequirement,
      roomModel: null,
    });
    const authoritativeScene = {
      id: 9,
      plan_version_id: 7,
      current_version: 2,
      scene: {
        schemaVersion: "1.0" as const,
        unit: "m" as const,
        coordinateSystem: "right-handed-y-up" as const,
        room: {
          id: "living-room",
          name: "客厅",
          floorPolygon: [
            { x: -3, z: -2 },
            { x: 3, z: -2 },
            { x: 3, z: 2 },
          ],
          ceilingHeight: 2.8,
          wallThickness: 0.12,
        },
        openings: [],
        items: [],
      },
      validation: { valid: true, errors: [], warnings: [] },
      source: "manual" as const,
    };

    useDesignProjectStore.getState().setAuthoritativeScene(49, authoritativeScene);

    expect(useDesignProjectStore.getState().projects[49]).toMatchObject({
      sceneRef: { scene_id: 9, version: 2 },
      authoritativeScene,
    });
  });

  it("从 checkpoint 恢复自定义家具规格、预览与审批状态", () => {
    useDesignProjectStore.getState().registerProject(43, "custom_furniture", {
      requirement: emptyRequirement,
      roomModel: null,
    });
    const customFurnitureSpec = {
      family: "table" as const,
      name: "六人位餐桌",
      purpose: "dining_table" as const,
      material: "实木（橡木）" as const,
      dimensions: { width_mm: 1600, height_mm: 750, depth_mm: 800 },
      structure: {
        top_shape: "rectangle" as const,
        base_style: "four_leg" as const,
        support_count: 4,
        seat_count: 6,
        top_thickness_mm: 36,
        edge_radius_mm: 12,
      },
    };
    const customFurnitureResult = {
      status: "needs_human" as const,
      spec: customFurnitureSpec,
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
      quote_preview: {
        status: "needs_human" as const,
        reason_code: "quote_rule_missing" as const,
        rule_id: null,
        project_name: "定制餐桌",
        material_grade: "实木（橡木）",
        pricing_unit: null,
        unit_price: null,
        quantity: null,
        estimated_amount: null,
        currency: "CNY" as const,
        description: null,
      },
      warnings: ["投产前仍需工程复核。"],
    };

    useDesignProjectStore.getState().applyAgentState(43, {
      stateVersion: 2,
      status: "needs_human",
      activeMode: "custom_furniture",
      pendingQuestions: [],
      sceneRef: null,
      exitReason: "approval_required",
      customFurnitureSpec,
      customFurnitureResult,
      approvalRequired: true,
    });

    expect(useDesignProjectStore.getState().projects[43]).toMatchObject({
      customFurnitureSpec,
      customFurnitureResult,
      approvalRequired: true,
    });
  });

  it("仅持久化已确认保存的定制草稿引用，并可在规格变化时清除", () => {
    useDesignProjectStore.getState().registerProject(48, "custom_furniture", {
      requirement: emptyRequirement,
      roomModel: null,
    });

    useDesignProjectStore.getState().setCustomFurnitureDraftReference(48, {
      clientMutationId: "draft-custom-001",
      specSignature: "stable-spec-signature",
    });
    expect(useDesignProjectStore.getState().projects[48]?.customFurnitureDraftReference)
      .toEqual({
        clientMutationId: "draft-custom-001",
        specSignature: "stable-spec-signature",
      });

    useDesignProjectStore.getState().setCustomFurnitureDraftReference(48, null);
    expect(useDesignProjectStore.getState().projects[48]?.customFurnitureDraftReference)
      .toBeNull();
  });

  it("恢复 Worker 运行引用并在挂载方案后保留 Agent 完成态", () => {
    useDesignProjectStore.getState().registerProject(45, "catalog_design", {
      requirement: emptyRequirement,
      roomModel: null,
    });
    useDesignProjectStore.getState().applyAgentState(45, {
      stateVersion: 3,
      status: "completed",
      activeMode: "catalog_design",
      pendingQuestions: [],
      sceneRef: null,
      exitReason: "goal_completed",
      generationRunId: 7,
    });

    useDesignProjectStore.getState().attachPlan(45, {
      id: "worker-plan",
      planVersionId: 11,
    });

    expect(useDesignProjectStore.getState().projects[45]).toMatchObject({
      status: "completed",
      generationRunId: 7,
      activePlanId: "worker-plan",
      activePlanVersionId: 11,
    });
  });

  it("把旧本地项目迁移为 v4 并补齐执行与定制草稿引用", async () => {
    const legacyProject = useDesignProjectStore
      .getState()
      .registerProject(47, "catalog_design", {
        requirement: emptyRequirement,
        roomModel: null,
      });
    const project = { ...useDesignProjectStore.getState().projects[legacyProject] };
    project.generationRunId = 9;
    Reflect.deleteProperty(project, "execution");
    const migrated = migrateDesignProjectState({
      projects: { 47: project },
      currentProjectId: 47,
    }, 2) as {
      projects: Record<number, {
        execution?: unknown;
        generationRunId?: number | null;
        customFurnitureDraftReference?: unknown;
      }>;
    };

    expect(migrated.projects[47]?.execution).toMatchObject({
      currentNode: "idle",
      stepCount: 0,
      events: [],
    });
    expect(migrated.projects[47]?.generationRunId).toBe(9);
    expect(migrated.projects[47]).toMatchObject({
      customFurnitureDraftReference: null,
    });
  });
});
