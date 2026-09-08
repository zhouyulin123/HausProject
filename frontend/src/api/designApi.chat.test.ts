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

  it("自定义家具规格仍通过统一 agent-turns 提交", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(jsonResponse({ reply: "参数已接收" }));
    vi.stubGlobal("window", { localStorage: createLocalStorage({}) });
    vi.stubGlobal("fetch", fetchMock);

    const { sendAgentTurn } = await import("./designApi");
    await sendAgentTurn(42, {
      client_turn_id: "custom-turn-001",
      message: "提交结构化定制参数",
      active_mode: "custom_furniture",
      custom_furniture_spec: {
        family: "table",
        name: "六人位餐桌",
        purpose: "dining_table",
        material: "实木（橡木）",
        dimensions: { width_mm: 1600, height_mm: 750, depth_mm: 800 },
        structure: {
          top_shape: "rectangle",
          base_style: "four_leg",
          support_count: 4,
          seat_count: 6,
          top_thickness_mm: 36,
          edge_radius_mm: 12,
        },
      },
    });

    const [path, init] = fetchMock.mock.calls[1]!;
    expect(String(path)).toBe("/api/design/tasks/42/agent-turns");
    expect(String(path)).not.toContain("custom-furniture-previews");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      active_mode: "custom_furniture",
      custom_furniture_spec: { family: "table", purpose: "dining_table" },
    });
  });

  it("方案精修和场景调整上下文均可通过统一 agent-turns 提交", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(jsonResponse({ reply: "已调整方案" }))
      .mockResolvedValueOnce(jsonResponse({ reply: "已调整场景" }));
    vi.stubGlobal("window", { localStorage: createLocalStorage({}) });
    vi.stubGlobal("fetch", fetchMock);

    const { sendAgentTurn } = await import("./designApi");
    await sendAgentTurn(42, {
      client_turn_id: "plan-refine-turn-001",
      message: "把主沙发换成浅灰色",
      active_mode: "catalog_design",
      plan_id: "plan-a",
    });
    await sendAgentTurn(42, {
      client_turn_id: "scene-edit-turn-001",
      message: "把沙发向左移动",
      active_mode: "catalog_design",
      scene_id: 9,
      base_scene_version: 3,
    });

    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toMatchObject({
      plan_id: "plan-a",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toMatchObject({
      scene_id: 9,
      base_scene_version: 3,
    });
    for (const [path] of fetchMock.mock.calls.slice(1)) {
      expect(String(path)).toBe("/api/design/tasks/42/agent-turns");
    }
  });
});
