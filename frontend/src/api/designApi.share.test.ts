import { afterEach, describe, expect, it, vi } from "vitest";


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


function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}


afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});


describe("方案所有者分享 API", () => {
  it("使用匿名会话创建明确方案版本的限时分享", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    vi.stubGlobal("window", {
      localStorage: createLocalStorage({
        "haus-anonymous-session-id": sessionId,
      }),
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response({ session_id: sessionId }))
      .mockResolvedValueOnce(
        response({
          token: "raw-token",
          share_url: "/share/raw-token",
          expires_at: "2026-09-10T00:00:00Z",
        }, 201),
      );
    vi.stubGlobal("fetch", fetchMock);

    const { createPlanShare } = await import("./designApi");
    const created = await createPlanShare(42, 24);

    expect(created.shareUrl).toBe("/share/raw-token");
    const [, init] = fetchMock.mock.calls[1];
    expect(fetchMock.mock.calls[1][0]).toBe("/api/design/shares");
    expect(new Headers(init?.headers).get("X-Session-ID")).toBe(sessionId);
    expect(JSON.parse(String(init?.body))).toEqual({
      plan_version_id: 42,
      expires_in_hours: 24,
    });
  });

  it("使用原始令牌撤销分享且不把令牌写入请求体", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    vi.stubGlobal("window", {
      localStorage: createLocalStorage({
        "haus-anonymous-session-id": sessionId,
      }),
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response({ session_id: sessionId }))
      .mockResolvedValueOnce(response({ status: "revoked" }));
    vi.stubGlobal("fetch", fetchMock);

    const { revokePlanShare } = await import("./designApi");
    await revokePlanShare("raw/token");

    const [, init] = fetchMock.mock.calls[1];
    expect(fetchMock.mock.calls[1][0]).toBe(
      "/api/design/shares/raw%2Ftoken/revoke",
    );
    expect(new Headers(init?.headers).get("X-Session-ID")).toBe(sessionId);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
  });
});
