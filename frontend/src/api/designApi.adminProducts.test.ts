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
    expect(JSON.parse(String(request?.body))).toMatchObject({
      id: 8,
      record_version: 4,
    });
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
});
