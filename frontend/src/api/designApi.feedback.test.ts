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

describe("设计反馈 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("向任务级 feedback-events 发送严格结构化事件", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: "session-001" }))
      .mockResolvedValueOnce(jsonResponse({
        id: 9,
        task_id: 42,
        client_event_id: "feedback-42-final-001",
        action_type: "final_select",
        plan_version_id: 8,
        scene_id: null,
        scene_version: null,
        room_id: null,
        instance_id: null,
        source_sku: null,
        target_sku: null,
        satisfaction_score: 4,
        created_at: "2026-09-02T09:00:00Z",
      }));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { sendDesignFeedbackEvent } = await import("./designApi");
    const response = await sendDesignFeedbackEvent(42, {
      client_event_id: "feedback-42-final-001",
      action_type: "final_select",
      plan_version_id: 8,
      satisfaction_score: 4,
    });

    expect(response.id).toBe(9);
    const [path, init] = fetchMock.mock.calls[1]!;
    expect(String(path)).toBe("/api/design/tasks/42/feedback-events");
    expect(JSON.parse(String(init?.body))).toEqual({
      client_event_id: "feedback-42-final-001",
      action_type: "final_select",
      plan_version_id: 8,
      satisfaction_score: 4,
    });
  });
});
