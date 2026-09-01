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

const cachedUser = {
  id: 1,
  phone: "13800000000",
  nickname: null,
  avatar: null,
  role: "customer",
};

describe("useAuthStore 登录恢复", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("后端暂时不可用时保留缓存用户和旧令牌", async () => {
    const storage = createLocalStorage({
      "haus-auth-token": "legacy-token",
      "haus-auth-user": JSON.stringify(cachedUser),
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));

    const { useAuthStore } = await import("./useAuthStore");
    await useAuthStore.getState().init();

    expect(useAuthStore.getState().user).toEqual(cachedUser);
    expect(storage.getItem("haus-auth-token")).toBe("legacy-token");
  });

  it("Cookie 登录没有旧令牌时仍会向后端恢复用户", async () => {
    const storage = createLocalStorage({
      "haus-auth-user": JSON.stringify(cachedUser),
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ user: cachedUser }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal("fetch", fetchMock);

    const { useAuthStore } = await import("./useAuthStore");
    await useAuthStore.getState().init();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/auth/me",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    expect(useAuthStore.getState().user).toEqual(cachedUser);
  });

  it("后端明确返回 401 时才清理登录态", async () => {
    const storage = createLocalStorage({
      "haus-auth-token": "expired-token",
      "haus-auth-user": JSON.stringify(cachedUser),
    });
    vi.stubGlobal("window", { localStorage: storage });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "未登录" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const { useAuthStore } = await import("./useAuthStore");
    await useAuthStore.getState().init();

    expect(useAuthStore.getState().user).toBeNull();
    expect(storage.getItem("haus-auth-token")).toBeNull();
  });
});
