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
});
