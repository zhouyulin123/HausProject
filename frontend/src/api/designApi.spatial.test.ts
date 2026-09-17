import { afterEach, describe, expect, it, vi } from "vitest";

const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
function setup(status = 200, body: unknown = { task_id: 42, version: 0, document: null, created_at: null }) {
  const values = new Map<string, string>();
  vi.stubGlobal("window", { localStorage: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  } });
  const fetchMock = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(new Response(JSON.stringify({ session_id: sessionId })))
    .mockImplementation(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("任务级整屋空间接口", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

  it("保留尚未创建的空间状态，并携带当前会话", async () => {
    const fetchMock = setup();
    const api = await import("./designApi");
    expect(await api.getTaskSpace(42)).toEqual({ task_id: 42, version: 0, document: null, created_at: null });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/design/tasks/42/space");
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-Session-ID")).toBe(sessionId);
  });

  it.each([404, 409, 422, 500])("直接报告 %s 错误，不返回虚构空间", async (status) => {
    const fetchMock = setup(status, { detail: "空间请求失败" });
    const api = await import("./designApi");
    await expect(api.getTaskSpace(42)).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
