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
    const updated = await updateDesignScene(9, 1, scene, "scene_agent");

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
        }),
      }),
    );
  });

  it("方案尚无场景时自动创建，避免调用方处理 404 分支", async () => {
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
      source: "manual" as const,
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
      "/api/design/plan-versions/7/scene",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
