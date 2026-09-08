import { afterEach, describe, expect, it, vi } from "vitest";

function createLocalStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
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

describe("统一任务时间线 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("携带 after_id 和有界 limit 并保留未知成本语义", async () => {
    const payload = {
      task_id: 42,
      events: [{
        event_id: 8,
        source_type: "generation",
        source_id: 3,
        attempt: 2,
        event_code: "generation.completed",
        summary: "方案生成完成",
        billing_status: "unknown",
        cost_cny: null,
        occurred_at: "2026-09-08T09:00:00Z",
      }],
      next_cursor: 8,
      known_cost_cny: null,
      has_unknown_cost: true,
      unknown_cost_event_count: 1,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: "session-001" }))
      .mockResolvedValueOnce(jsonResponse(payload));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchDesignTaskTimeline } = await import("./designApi");
    await expect(fetchDesignTaskTimeline(42, { afterId: 5, limit: 25 }))
      .resolves.toEqual(payload);
    expect(String(fetchMock.mock.calls[1]?.[0]))
      .toBe("/api/design/tasks/42/timeline?limit=25&after_id=5");
  });
});
