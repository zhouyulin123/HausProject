import { afterEach, describe, expect, it, vi } from "vitest";

function createLocalStorage(initial: Record<string, string>): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const scene = {
  schemaVersion: "1.0" as const,
  unit: "m" as const,
  coordinateSystem: "right-handed-y-up" as const,
  room: {
    id: "living-room",
    name: "客厅",
    floorPolygon: [
      { x: 0, z: 0 },
      { x: 5, z: 0 },
      { x: 5, z: 4 },
    ],
    ceilingHeight: 2.8,
    wallThickness: 0.12,
  },
  openings: [],
  items: [],
};

describe("3D 场景 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("使用方案版本编号创建并更新场景", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: 9,
          plan_version_id: 7,
          current_version: 1,
          scene,
          validation: { valid: true, errors: [], warnings: [] },
          source: "manual",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: 9,
          plan_version_id: 7,
          current_version: 1,
          scene,
          validation: { valid: true, errors: [], warnings: [] },
          source: "manual",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: 9,
          plan_version_id: 7,
          current_version: 2,
          scene,
          validation: { valid: true, errors: [], warnings: [] },
          source: "scene_agent",
        }),
      );
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const {
      createDesignScene,
      fetchDesignSceneByPlanVersion,
      updateDesignScene,
    } = await import("./designApi");
    const created = await createDesignScene(7, scene);
    const restored = await fetchDesignSceneByPlanVersion(7);
    const updated = await updateDesignScene(9, 1, scene, "scene_agent", {
      clientMutationId: "move-request-001",
      movedInstanceIds: [],
      roomId: "living-room",
    });

    expect(created.current_version).toBe(1);
    expect(restored.id).toBe(9);
    expect(updated.current_version).toBe(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/design/plan-versions/7/scene",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ scene, source: "manual" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/design/plan-versions/7/scene",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/design/scenes/9",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          base_version: 1,
          scene,
          source: "scene_agent",
          client_mutation_id: "move-request-001",
          moved_instance_ids: [],
          feedback_room_id: "living-room",
        }),
      }),
    );
  });

  it("把已保存定制草稿以幂等请求加入当前场景", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const addedScene = {
      id: 9,
      plan_version_id: 7,
      current_version: 2,
      scene,
      validation: { valid: true, errors: [], warnings: [] },
      source: "manual" as const,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(jsonResponse(addedScene));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { addCustomFurnitureDraftToScene } = await import("./designApi");
    const result = await addCustomFurnitureDraftToScene(9, {
      baseVersion: 1,
      clientMutationId: "place-custom-001",
      draftClientMutationId: "draft-custom-001",
      position: { x: 0, z: 0 },
      rotationY: 0.25,
    });

    expect(result).toEqual(addedScene);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/design/scenes/9/custom-furniture-items",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          baseVersion: 1,
          clientMutationId: "place-custom-001",
          draftClientMutationId: "draft-custom-001",
          position: { x: 0, z: 0 },
          rotationY: 0.25,
        }),
      }),
    );
  });

  it("将草稿 409 解析为带权威服务端快照的冲突", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const conflict = new Response(JSON.stringify({
      detail: {
        code: "agent_state_conflict",
        message: "草稿版本冲突",
        state_version: 8,
        custom_furniture_draft: { family: "table", name: "服务端草稿" },
        scene_ref: { scene_id: 12, version: 4 },
      },
    }), {
      status: 409,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(conflict);
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);
    const { saveCustomFurnitureDraft } = await import("./designApi");

    await expect(saveCustomFurnitureDraft(42, {
      clientMutationId: "draft-conflict-001",
      baseStateVersion: 7,
      spec: { family: "table", name: "本地草稿" },
    })).rejects.toMatchObject({
      conflict: {
        stateVersion: 8,
        customFurnitureDraft: { family: "table", name: "服务端草稿" },
        sceneRef: { scene_id: 12, version: 4 },
      },
    });
  });

  it("方案商品变更和定制草稿只调用服务端版本化入口", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const plan = {
      id: "plan-a",
      planVersionId: 12,
      name: "方案 A",
      style: "现代",
      coverGradient: "",
      score: 90,
      budget: 8000,
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
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(jsonResponse({
        revision_version: 3,
        plan,
        scene: {
          id: 15,
          plan_version_id: 12,
          current_version: 1,
          scene,
          validation: { valid: true, errors: [], warnings: [] },
          source: "manual",
        },
        feedback: {},
      }))
      .mockResolvedValueOnce(jsonResponse({
        task_id: 42,
        state_version: 5,
        custom_furniture_spec: { family: "table" },
      }));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { mutateWorkspacePlan, saveCustomFurnitureDraft } = await import("./designApi");
    const mutation = await mutateWorkspacePlan(42, {
      clientMutationId: "adopt-request-001",
      baseRevisionVersion: 2,
      planVersionId: 10,
      action: "adopt",
      targetSku: "TABLE-001",
      roomId: "living-room",
    });
    await saveCustomFurnitureDraft(42, {
      clientMutationId: "draft-request-001",
      baseStateVersion: 4,
      spec: { family: "table" },
    });

    expect(mutation.plan.revisionVersion).toBe(3);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/design/tasks/42/plan-mutations",
      expect.objectContaining({
        body: expect.stringContaining('"placement_mode":"auto_place"'),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/design/tasks/42/custom-furniture-draft",
      expect.objectContaining({
        body: expect.stringContaining('"base_state_version":4'),
      }),
    );
  });

  it("方案尚无场景时优先由后端 auto-layout 自动创建", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const notFound = new Response(JSON.stringify({ detail: "不存在" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
    const created = {
      id: 9,
      plan_version_id: 7,
      current_version: 1,
      scene,
      validation: { valid: true, errors: [], warnings: [] },
      source: "auto_layout" as const,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(notFound)
      .mockResolvedValueOnce(jsonResponse(created));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { loadOrCreateDesignScene } = await import("./designApi");
    const result = await loadOrCreateDesignScene(7, scene);

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/design/plan-versions/7/auto-layout",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("auto-layout 不可用时回退前端初始布局创建场景", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const notFound = new Response(JSON.stringify({ detail: "不存在" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
    const unsupported = new Response(
      JSON.stringify({ detail: "方案没有可用于布局的商品" }),
      { status: 422, headers: { "Content-Type": "application/json" } },
    );
    const created = {
      id: 9,
      plan_version_id: 7,
      current_version: 1,
      scene,
      validation: { valid: true, errors: [], warnings: [] },
      source: "manual" as const,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(notFound)
      .mockResolvedValueOnce(unsupported)
      .mockResolvedValueOnce(jsonResponse(created));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { loadOrCreateDesignScene } = await import("./designApi");
    const result = await loadOrCreateDesignScene(7, scene);

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/design/plan-versions/7/scene",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("首次场景恢复失败后允许重新发起恢复请求", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const unavailable = new Response(JSON.stringify({ detail: "暂时不可用" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
    const restored = {
      id: 9,
      plan_version_id: 7,
      current_version: 1,
      scene,
      validation: { valid: true, errors: [], warnings: [] },
      source: "auto_layout" as const,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(unavailable)
      .mockResolvedValueOnce(jsonResponse(restored));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { loadOrCreateDesignScene } = await import("./designApi");

    await expect(loadOrCreateDesignScene(7, scene)).rejects.toMatchObject({
      status: 503,
    });
    await expect(loadOrCreateDesignScene(7, scene)).resolves.toEqual(restored);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/design/plan-versions/7/scene",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
  });

  it("提交自然语言场景命令并返回新的场景版本", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(
        jsonResponse({
          message: "已将沙发向左移动",
          operations: [
            {
              type: "move",
              instanceId: "sofa-main",
              position: { x: 1.5, z: 0 },
            },
          ],
          scene: {
            id: 9,
            plan_version_id: 5,
            current_version: 2,
            scene,
            validation: { valid: true, errors: [], warnings: [] },
            source: "scene_agent",
          },
        }),
      );
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { runSceneAgentCommand } = await import("./designApi");
    const result = await runSceneAgentCommand(9, 1, "把沙发向左移动");

    expect(result.scene.current_version).toBe(2);
    expect(result.message).toContain("向左移动");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/design/scenes/9/agent-command",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          baseVersion: 1,
          instruction: "把沙发向左移动",
        }),
      }),
    );
  });

  it("demo 场景命令携带最近的结构化执行历史", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const history = [
      {
        instruction: "加一把餐椅",
        message: "已添加餐椅",
        operations: [
          {
            type: "add" as const,
            sku: "CY-001",
            position: { x: 0, z: 0.75 },
            rotationY: 0,
          },
        ],
        affectedInstanceIds: ["item-CY-001-1"],
      },
    ];
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(
        jsonResponse({ message: "已移走", operations: [], scene }),
      );
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { runDemoAgentCommand } = await import("./designApi");
    await runDemoAgentCommand("把刚才那个移走", scene, history);

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/demo/agent-command",
      expect.objectContaining({
        body: JSON.stringify({
          instruction: "把刚才那个移走",
          scene,
          history,
        }),
      }),
    );
  });

  it("严格商品库模式在后端失败时拒绝静默 mock 降级", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const unavailable = new Response(JSON.stringify({ detail: "不可用" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(unavailable);
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchFurnitureCatalog } = await import("./designApi");

    await expect(
      fetchFurnitureCatalog({ fallbackToMock: false }),
    ).rejects.toThrow("商品库加载失败");
  });

  it("保留后端审核后的商品资产展示契约", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(
        jsonResponse({
          products: [
            {
              id: 1,
              sku: "SOFA-001",
              name: "审核沙发",
              category: "沙发",
              room: "客厅",
              style: "现代简约",
              material: "布艺",
              price_text: "¥6,800",
              size: "2200×850×950mm",
              selling_point: "",
              alternative: "",
              image_url: null,
              model_url: "/uploads/models/sofa.glb",
              model_status: "ready",
              model_width_mm: 2200,
              model_height_mm: 850,
              model_depth_mm: 950,
              model_license: "供应商书面商用授权",
              model_source: "supplier:SOFA-001",
              model_spec_json: null,
              asset_mode: "approved_glb",
              fallback_reason: null,
              data_origin: "merchant",
              source_name: null,
              source_url: null,
              eligibility: {
                eligible: false,
                reason_codes: ["verification_required"],
              },
            },
          ],
        }),
      );
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchFurnitureCatalog } = await import("./designApi");
    const [product] = await fetchFurnitureCatalog({ fallbackToMock: false });

    expect(product.assetMode).toBe("approved_glb");
    expect(product.fallbackReason).toBeUndefined();
    expect(product.matchScore).toBeUndefined();
    expect(product.catalogEligibility).toEqual({
      eligible: false,
      reasonCodes: ["verification_required"],
    });
  });

  it("未显式开启 Demo 模式时商品库默认拒绝静默 mock 降级", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const unavailable = new Response(JSON.stringify({ detail: "不可用" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(unavailable);
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchFurnitureCatalog } = await import("./designApi");

    await expect(fetchFurnitureCatalog()).rejects.toThrow("商品库加载失败");
  });

  it("创建并轮询绑定场景版本的 Blender 渲染任务", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const queued = {
      id: 12,
      scene_id: 9,
      scene_version: 3,
      profile: "final" as const,
      status: "queued" as const,
      progress: 0,
      attempt: 0,
      output_url: null,
      error_message: null,
    };
    const completed = {
      ...queued,
      status: "completed" as const,
      progress: 100,
      output_url: "/uploads/blender_renders/scene_9_v3_final.png",
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(jsonResponse(queued))
      .mockResolvedValueOnce(jsonResponse(completed));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { createBlenderRenderJob, fetchBlenderRenderJob } =
      await import("./designApi");
    const created = await createBlenderRenderJob(9, 3, "final");
    const restored = await fetchBlenderRenderJob(9, created.id);

    expect(restored.output_url).toContain("scene_9_v3_final.png");
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/design/scenes/9/render-jobs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          baseVersion: 3,
          profile: "final",
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/design/scenes/9/render-jobs/12",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
  });
});
