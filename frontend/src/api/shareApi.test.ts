import { afterEach, describe, expect, it, vi } from "vitest";


afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});


describe("公开分享 API", () => {
  it("只用 URL token 读取服务端响应，不附加会话或本地数据", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          expires_at: "2026-09-04T00:00:00Z",
          plan: { name: "冻结方案", style: "原木风", budget: 100000 },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { fetchPublicPlanShare } = await import("./shareApi");
    const result = await fetchPublicPlanShare("token/with?reserved");

    expect(result.plan.name).toBe("冻结方案");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/shares/token%2Fwith%3Freserved",
      expect.objectContaining({ headers: expect.any(Headers) }),
    );
    const headers = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(headers.has("X-Session-ID")).toBe(false);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("失效链接返回统一的用户可见错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ detail: { code: "share_unavailable" } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const { fetchPublicPlanShare, PublicShareUnavailableError } = await import(
      "./shareApi"
    );

    await expect(fetchPublicPlanShare("expired-token")).rejects.toBeInstanceOf(
      PublicShareUnavailableError,
    );
  });
});
