import { afterEach, describe, expect, it, vi } from "vitest";

const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
const document = {
  schema_version: "spatial/1.0" as const,
  unit: "m" as const,
  scale_status: "unconfirmed" as const,
  source_image_id: null,
  rooms: [{ id: "room-a", name: "客厅", height: 2.8, polygon: [
    { x: -3, z: 2 }, { x: 1, z: 2 }, { x: 1, z: 5 }, { x: -3, z: 5 },
  ] }],
  walls: [],
  openings: [],
};
function setup(status = 200, body: unknown = { task_id: 42, version: 0, document: null }) {
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
    expect(await api.getTaskSpace(42)).toEqual({ task_id: 42, version: 0, document: null });
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/design/tasks/42/space");
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("X-Session-ID")).toBe(sessionId);
  });

  it("读取已保存文档并保留全局坐标和待确认尺度", async () => {
    const response = { task_id: 42, version: 3, document };
    setup(200, response);
    const api = await import("./designApi");
    expect(await api.getTaskSpace(42)).toEqual(response);
  });

  it("分页读取历史并按精确版本恢复，不把历史当当前版本", async () => {
    const fetchMock = setup(200, { task_id: 42, versions: [], next_before_version: null });
    const api = await import("./designApi");
    await api.getTaskSpaceVersions(42, 7);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/design/tasks/42/space/versions?limit=20&before_version=7");
    await api.getTaskSpaceVersion(42, 3);
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/design/tasks/42/space/versions/3");
  });

  it("保存原始文档、基准版本和调用方幂等键，同请求重试不换键", async () => {
    const response = { task_id: 42, version: 4, document };
    const fetchMock = setup(200, response);
    const api = await import("./designApi");
    const payload = { base_version: 3, client_mutation_id: "space-edit-42", document };
    const before = JSON.stringify(payload);
    expect(await api.saveTaskSpace(42, payload)).toEqual(response);
    expect(await api.saveTaskSpace(42, payload)).toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [url, init] of fetchMock.mock.calls.slice(1)) {
      expect(url).toBe("/api/design/tasks/42/space");
      expect(init?.method).toBe("PUT");
      expect(init?.body).toBe(before);
      expect(new Headers(init?.headers).get("X-Session-ID")).toBe(sessionId);
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    }
    expect(JSON.stringify(payload)).toBe(before);
  });

  it.each([404, 409, 422, 500])("保存失败 %s 保留服务端详情和原请求，不自动重试", async (status) => {
    const detail = { code: "space_rejected", message: "空间请求失败" };
    const fetchMock = setup(status, { detail });
    const api = await import("./designApi");
    const payload = { base_version: 3, client_mutation_id: "space-edit-42", document };
    const before = JSON.stringify(payload);
    await expect(api.saveTaskSpace(42, payload)).rejects.toMatchObject({ status, detail });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(payload)).toBe(before);
  });

  it.each([404, 409, 422, 500])("直接报告 %s 错误，不返回虚构空间", async (status) => {
    const fetchMock = setup(status, { detail: "空间请求失败" });
    const api = await import("./designApi");
    await expect(api.getTaskSpace(42)).rejects.toMatchObject({ status });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
