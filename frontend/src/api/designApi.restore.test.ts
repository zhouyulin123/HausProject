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
      renovationType: "全屋装修",
      budgetRange: "8-15 万",
      familySize: 2,
      hasChildren: false,
      hasPets: false,
      hasElderly: false,
      needStorage: true,
      styles: ["现代简约"],
      extraNotes: "",
    });

    expect(plans.map((item) => item.id)).toEqual(["plan-a"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/design/tasks/42/generate-async",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/design/tasks/42/generate",
      expect.anything(),
    );
  });
});
