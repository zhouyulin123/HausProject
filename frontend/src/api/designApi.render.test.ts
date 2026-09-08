import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

function createLocalStorage(initial: Record<string, string>): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}


function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


describe("异步效果图 API", () => {
  it("入队时发送稳定幂等键并返回 Job", async () => {
    const storage = createLocalStorage({
      "haus-anonymous-session-id": "session-a",
      "haus-current-task-id": "7",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ session_id: "session-a" }))
      .mockResolvedValueOnce(response({
        job_id: 12,
        request_id: "effect-trace-001",
        status: "queued",
        progress: 0,
        scene_id: 9,
        scene_version: 3,
      }, 202));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { queueEffectRender } = await import("./designApi");

    const job = await queueEffectRender(42, 9, 3, "render-key-1");

    expect(job.jobId).toBe(12);
    expect(job.requestId).toBe("effect-trace-001");
    expect(job).toMatchObject({ sceneId: 9, sceneVersion: 3 });
    const [, request] = fetchMock.mock.calls.at(-1)!;
    expect(new Headers(request.headers).get("Idempotency-Key")).toBe("render-key-1");
    expect(JSON.parse(String(request.body))).toMatchObject({
      plan_version_id: 42,
      scene_id: 9,
      scene_version: 3,
    });
  });

  it("支持按 Job、方案版本恢复以及取消", async () => {
    const storage = createLocalStorage({
      "haus-anonymous-session-id": "session-a",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ session_id: "session-a" }))
      .mockResolvedValueOnce(response({ job_id: 12, status: "running", progress: 50, scene_id: 9, scene_version: 3 }))
      .mockResolvedValueOnce(response({ job_id: 12, status: "completed", progress: 100, image_url: "/uploads/a.png", mode: "text2img", scene_id: 9, scene_version: 3 }))
      .mockResolvedValueOnce(response({ job_id: 12, status: "cancelled", progress: 100, scene_id: 9, scene_version: 3 }));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const {
      cancelEffectRender,
      fetchEffectRender,
      fetchLatestEffectRender,
    } = await import("./designApi");

    expect((await fetchEffectRender(12)).status).toBe("running");
    expect((await fetchLatestEffectRender(42, 9, 3))?.imageUrl).toBe("/uploads/a.png");
    expect(fetchMock.mock.calls[2][0]).toBe(
      "/api/design/render?plan_version_id=42&scene_id=9&scene_version=3",
    );
    expect((await cancelEffectRender(12)).status).toBe("cancelled");
  });
});
