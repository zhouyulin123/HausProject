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

describe("方案结果恢复", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("使用本地任务编号从服务端恢复已生成方案", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
      "haus-current-task-id": "42",
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(
        jsonResponse({
          task_id: 42,
          status: "completed",
          generator: "deepseek",
          revision_version: 2,
          plans: [
            {
              id: "plan-a",
              name: "温馨原木方案",
              style: "原木风",
              coverGradient: "",
              score: 92,
              budget: 120000,
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
            },
          ],
        }),
      );
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { restoreCurrentDesigns } = await import("./designApi");
    const plans = await restoreCurrentDesigns();

    expect(plans?.map((plan) => plan.id)).toEqual(["plan-a"]);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/design/tasks/42/result",
      expect.objectContaining({
        headers: expect.any(Headers),
      }),
    );
  });

  it("创建项目时把入口模式写入服务端任务", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/sessions/${sessionId}`) {
        return jsonResponse({ session_id: sessionId });
      }
      if (path === "/api/design/tasks") {
        return jsonResponse({ task_id: 42, status: "confirmed" });
      }
      throw new Error(`未处理的请求: ${path}`);
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { createDesignTask } = await import("./designApi");
    await createDesignTask(
      {
        rooms: ["书房"],
        area: 12,
        houseType: "两室一厅",
        city: "杭州",
        renovationType: "局部改造",
        budgetRange: "3-5 万",
        familySize: 2,
        hasChildren: false,
        hasPets: false,
        hasElderly: false,
        workFromHome: true,
        cookingOften: false,
        needStorage: true,
        ecoFriendly: true,
        smartHome: false,
        styles: ["现代简约"],
        colors: [],
        dislikedColors: [],
        materials: ["实木"],
        extraNotes: "定制书桌",
      },
      "custom_furniture",
    );

    const [, taskInit] = fetchMock.mock.calls.find(
      ([input]) => String(input) === "/api/design/tasks",
    ) ?? [];
    expect(JSON.parse(String(taskInit?.body))).toMatchObject({
      active_mode: "custom_furniture",
    });
  });

  it("通过后台任务生成并在完成后读取方案", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({});
    const plan = {
      id: "plan-a",
      name: "后台生成方案",
      style: "现代简约",
      coverGradient: "",
      score: 90,
      budget: 100000,
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
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === "/api/sessions") {
        return jsonResponse({ session_id: sessionId });
      }
      if (path === "/api/design/tasks") {
        return jsonResponse({ task_id: 42, status: "confirmed" });
      }
      if (path === "/api/design/tasks/42/generate-async") {
        return jsonResponse({ run_id: 7, status: "queued" });
      }
      if (path === "/api/design/tasks/42/generation") {
        return jsonResponse({
          run_id: 7,
          attempt: 1,
          status: "completed",
          progress: 100,
          current_node: "completed",
          generator: "llm",
          error_message: null,
          events: [],
        });
      }
      if (path === "/api/design/tasks/42/result") {
        return jsonResponse({ plans: [plan], generator: "llm" });
      }
      throw new Error(`未处理的请求: ${path} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { generateDesigns } = await import("./designApi");
    const plans = await generateDesigns({
      rooms: ["客厅"],
      area: 80,
      houseType: "两室一厅",
      city: "杭州",
      renovationType: "全屋装修",
      budgetRange: "8-15 万",
      familySize: 2,
      hasChildren: false,
      hasPets: false,
      hasElderly: false,
      workFromHome: false,
      cookingOften: true,
      needStorage: true,
      ecoFriendly: true,
      smartHome: false,
      styles: ["现代简约"],
      colors: [],
      dislikedColors: [],
      materials: [],
      extraNotes: "",
    });

    expect(plans.map((item) => item.id)).toEqual(["plan-a"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/design/tasks/42/generate-async",
      expect.objectContaining({
        method: "POST",
        headers: expect.any(Headers),
      }),
    );
    const generateCall = fetchMock.mock.calls.find(
      ([input]) => String(input) === "/api/design/tasks/42/generate-async",
    );
    const generateHeaders = new Headers(generateCall?.[1]?.headers);
    expect(generateHeaders.get("Idempotency-Key")).toBe(
      "design-generation-task-42-v1",
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/design/tasks/42/generate",
      expect.anything(),
    );
  });

  it.each([
    ["dead_letter", "供应商调用超过硬截止时间"],
    ["cancelled", "方案生成已取消"],
    ["cost_limit_exceeded", "模型调用将超过单任务成本上限，需人工确认"],
    ["provider_unavailable", "模型供应商暂时不可用，需要人工处理"],
  ] as const)("生成任务进入 %s 后立即停止轮询", async (status, expected) => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({
      "haus-anonymous-session-id": sessionId,
    });
    let statusPolls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/sessions/${sessionId}`) {
        return jsonResponse({ session_id: sessionId });
      }
      if (path === "/api/design/tasks/42/generate-async") {
        return jsonResponse({ run_id: 7, status: "queued" });
      }
      if (path === "/api/design/tasks/42/generation") {
        statusPolls += 1;
        return jsonResponse({
          run_id: 7,
          attempt: 1,
          status,
          progress: 100,
          current_node: status,
          generator: null,
          error_message:
            status === "dead_letter"
              ? "供应商调用超过硬截止时间"
              : status === "cost_limit_exceeded"
                ? "模型调用将超过单任务成本上限，需人工确认"
                : null,
          execution_deadline_at: "2026-09-02T04:00:00Z",
          dead_lettered_at:
            status === "dead_letter" ? "2026-09-02T04:00:00Z" : null,
          events: [],
        });
      }
      throw new Error(`未处理的请求: ${path}`);
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { generateDesignsForTask } = await import("./designApi");

    await expect(generateDesignsForTask(42)).rejects.toThrow(expected);
    expect(statusPolls).toBe(1);
  });

  it("恢复 Agent 排队生成并在 Worker 成功后读取方案和最新状态", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({ "haus-anonymous-session-id": sessionId });
    const checkpoint = {
      task_id: 42,
      state_version: 3,
      status: "completed",
      active_mode: "catalog_design",
      active_room_id: null,
      intent: "design",
      current_node: "generation_completed",
      facts: {},
      fact_evidence: {},
      pending_questions: [],
      step_count: 5,
      retry_count: 0,
      max_steps: 12,
      max_retries: 2,
      hard_errors: [],
      custom_furniture_spec: null,
      approval_required: false,
      exit_reason: "goal_completed",
      scene_ref: null,
      run_id: 7,
      result: { run_id: 7, generation_status: "completed" },
      messages: [],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/sessions/${sessionId}`) return jsonResponse({ session_id: sessionId });
      if (path === "/api/design/tasks/42/generation") {
        return jsonResponse({ run_id: 7, status: "completed", progress: 100 });
      }
      if (path === "/api/design/tasks/42/agent-state") return jsonResponse(checkpoint);
      if (path === "/api/design/tasks/42/result") {
        return jsonResponse({ plans: [{ id: "worker-plan" }], generator: "llm" });
      }
      throw new Error(`未处理的请求: ${path}`);
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { resumeAgentGeneration } = await import("./designApi");
    const result = await resumeAgentGeneration(42, 7);

    expect(result.checkpoint).toEqual(checkpoint);
    expect(result.plans.map((plan) => plan.id)).toEqual(["worker-plan"]);
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/design/tasks/42/agent-turns",
      expect.anything(),
    );
  });

  it("Worker 终态失败后恢复 needs_human 且不读取伪方案", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const storage = createLocalStorage({ "haus-anonymous-session-id": sessionId });
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      if (path === `/api/sessions/${sessionId}`) return jsonResponse({ session_id: sessionId });
      if (path === "/api/design/tasks/42/generation") {
        return jsonResponse({
          run_id: 7,
          status: "provider_unavailable",
          progress: 100,
          error_message: "模型供应商暂时不可用",
        });
      }
      if (path === "/api/design/tasks/42/agent-state") {
        return jsonResponse({
          task_id: 42,
          state_version: 3,
          status: "needs_human",
          exit_reason: "generation_failed",
          run_id: 7,
          result: { run_id: 7, generation_status: "provider_unavailable" },
          messages: [],
        });
      }
      throw new Error(`未处理的请求: ${path}`);
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { resumeAgentGeneration } = await import("./designApi");
    const result = await resumeAgentGeneration(42, 7);

    expect(result.checkpoint.status).toBe("needs_human");
    expect(result.plans).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/design/tasks/42/result",
      expect.anything(),
    );
  });
});
