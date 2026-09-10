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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("商品商业核验管理 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("从受保护的完整商品目录读取核验事实", async () => {
    const storage = createLocalStorage();
    storage.setItem("haus-auth-token", "factory-token");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ products: [], count: 0 }));
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchAdminProducts } = await import("./designApi");
    await expect(fetchAdminProducts()).resolves.toEqual([]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/products/admin/catalog");
    expect(new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("Authorization"))
      .toBe("Bearer factory-token");
  });

  it("更新商品时提交当前记录版本，避免覆盖其他运营人员的修改", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ id: 8, name: "核验沙发", record_version: 5 }));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { saveProduct } = await import("./designApi");
    await saveProduct({ id: 8, name: "核验沙发", price: 4999, record_version: 4 });

    const request = fetchMock.mock.calls[0]?.[1];
    expect(request?.method).toBe("PATCH");
    const payload = JSON.parse(String(request?.body));
    expect(payload).toMatchObject({ record_version: 4 });
    expect(payload).not.toHaveProperty("id");
  });

  it("按地区读取目录就绪度，不在前端伪造统计", async () => {
    const readiness = {
      checked_at: "2026-09-08T12:00:00Z",
      region: "CN-SH",
      total: 57,
      active_total: 57,
      inactive_total: 0,
      eligible_total: 12,
      ineligible_total: 45,
      verification_status_counts: { draft: 40, verified: 17 },
      availability_status_counts: { unknown: 40, in_stock: 17 },
      data_origin_counts: { merchant_draft: 40, merchant: 17 },
      reason_code_counts: { verification_required: 40 },
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readiness));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchAdminCatalogReadiness } = await import("./designApi");
    await expect(fetchAdminCatalogReadiness("cn-sh")).resolves.toEqual(readiness);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/products/admin/readiness?region=CN-SH",
    );
  });

  it("商业审核提交记录版本与稳定幂等键", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({
      id: 31,
      product_id: 8,
      event_type: "commercial_review_approve",
      actor: "user:1",
      request_id: "product:request-1",
      changed_fields: ["verification_status"],
      changes: {},
      decision: "approve",
      resulting_status: "verified",
      resulting_record_version: 5,
      created_at: "2026-09-10T08:00:00Z",
    }));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { reviewProductCommercially } = await import("./designApi");
    await reviewProductCommercially(
      8,
      { decision: "approve", expectedRecordVersion: 4 },
      "commercial-review-8-v4-request-1",
    );

    const [path, request] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/products/8/commercial-review");
    expect(request?.method).toBe("POST");
    expect(new Headers(request?.headers).get("Idempotency-Key")).toBe(
      "commercial-review-8-v4-request-1",
    );
    expect(JSON.parse(String(request?.body))).toEqual({
      decision: "approve",
      expected_record_version: 4,
    });
  });

  it("拒绝原因只通过请求体提交，不进入 URL 或幂等键", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse({
      id: 32,
      product_id: 8,
      event_type: "commercial_review_reject",
      actor: "user:1",
      request_id: "product:request-2",
      changed_fields: ["review_note"],
      changes: {},
      decision: "reject",
      resulting_status: "rejected",
      resulting_record_version: 5,
      created_at: "2026-09-10T08:00:00Z",
    }));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { reviewProductCommercially } = await import("./designApi");
    await reviewProductCommercially(
      8,
      { decision: "reject", expectedRecordVersion: 4, note: "来源无法复核" },
      "commercial-review-8-v4-reject-1",
    );

    const [path, request] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/products/8/commercial-review");
    expect(new Headers(request?.headers).get("Idempotency-Key")).toBe(
      "commercial-review-8-v4-reject-1",
    );
    expect(JSON.parse(String(request?.body))).toEqual({
      decision: "reject",
      expected_record_version: 4,
      note: "来源无法复核",
    });
  });

  it("读取厂家可见的真实商品审计时间线", async () => {
    const response = { items: [], count: 0 };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValueOnce(jsonResponse(response));
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { fetchProductAuditEvents } = await import("./designApi");
    await expect(fetchProductAuditEvents(8, 50)).resolves.toEqual(response);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/products/8/audit-events?limit=50",
    );
  });
});
