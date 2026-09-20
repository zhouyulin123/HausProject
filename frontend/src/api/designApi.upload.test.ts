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

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("项目级房间上传", () => {
  it("读取原图只使用鉴权请求，不把会话放进地址", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({session_id: sessionId}))
      .mockResolvedValueOnce(new Response(new Blob(['image'], {type: 'image/png'}), {headers: {'Content-Type':'image/png'}}));
    vi.stubGlobal('window', {localStorage: createLocalStorage()});
    vi.stubGlobal('fetch', fetchMock);
    const {fetchUploadedImageContent} = await import('./designApi');
    expect((await fetchUploadedImageContent(8)).type).toBe('image/png');
    expect(fetchMock.mock.calls[1][0]).toBe('/api/upload/images/8/content');
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('X-Session-ID')).toBe(sessionId);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("把 DesignTask 编号随图片一并提交", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ session_id: sessionId }))
      .mockResolvedValueOnce(
        jsonResponse({
          image_id: 8,
          image_url: "/uploads/8-room.png",
          analysis: { findings: [], source: "vl", room_model: null },
        }),
      );
    vi.stubGlobal("window", { localStorage: createLocalStorage() });
    vi.stubGlobal("fetch", fetchMock);

    const { analyzeRoomImage } = await import("./designApi");
    const result = await analyzeRoomImage(new File(["image"], "客厅.png", { type: "image/png" }), 42);
    expect(result.imageUrl).toBe("/uploads/8-room.png");

    const body = fetchMock.mock.calls[1]?.[1]?.body;
    const headers = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("task_id")).toBe("42");
    expect(headers.get("Idempotency-Key")).toMatch(/^upload-42-[a-f0-9]{64}$/);
  });
});
