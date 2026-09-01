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

describe("项目级智能体轮次", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("显式发送当前项目任务号和该项目对话历史", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(jsonResponse({ reply: "已保留电视柜" }));
    vi.stubGlobal("window", { localStorage: createLocalStorage({}) });
    vi.stubGlobal("fetch", fetchMock);

    const { sendAgentTurn } = await import("./designApi");
    const result = await sendAgentTurn(42, {
      client_turn_id: "turn-42-1",
      message: "沙发换小一点",
      active_mode: "catalog_design",
    });

    expect(result.reply).toBe("已保留电视柜");
    const request = fetchMock.mock.calls[1];
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      client_turn_id: "turn-42-1",
      message: "沙发换小一点",
      active_mode: "catalog_design",
    });
    expect(String(request?.[0])).toBe("/api/design/tasks/42/agent-turns");
  });
});
