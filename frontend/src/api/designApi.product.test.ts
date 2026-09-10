import { afterEach, describe, expect, it, vi } from "vitest";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("商品停用 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("发送当前记录版本和调用方稳定幂等键", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ event_type: "commercial_deactivate" }),
    );
    vi.stubGlobal("window", { localStorage: null });
    vi.stubGlobal("fetch", fetchMock);

    const { deleteProduct } = await import("./designApi");
    await deleteProduct(17, 4, "deactivate-17-v4-request-1");

    const [path, init] = fetchMock.mock.calls[0]!;
    expect(String(path)).toBe("/api/products/17?expected_record_version=4");
    expect(init?.method).toBe("DELETE");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe(
      "deactivate-17-v4-request-1",
    );
  });

  it("商品编辑只发送可写白名单，不回传核验状态和服务端派生字段", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({ id: 17 }),
    );
    vi.stubGlobal("window", { localStorage: null });
    vi.stubGlobal("fetch", fetchMock);

    const { saveProduct } = await import("./designApi");
    await saveProduct({
      id: 17,
      name: "餐桌",
      price: 3200,
      record_version: 4,
      verification_status: "verified",
      verified_at: "2026-09-01T00:00:00Z",
      verified_by: "user:1",
      price_text: "¥3,200",
      eligibility: { eligible: true, reason_codes: [] },
    });

    const payload = JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body));
    expect(payload).toEqual({
      name: "餐桌",
      price: 3200,
      record_version: 4,
    });
  });
});
