import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";


describe("公开分享页数据边界", () => {
  it("只依赖公开分享 API，不导入本地 store 或 mock", () => {
    const page = readFileSync(new URL("./SharePage.tsx", import.meta.url), "utf-8");

    expect(page).toContain('from "@/api/shareApi"');
    expect(page).not.toContain("@/store/");
    expect(page).not.toContain("@/data/mock");
    expect(page).not.toContain("localStorage");
    expect(page).not.toContain("sessionStorage");
    expect(page).not.toContain("plan.score");
    expect(page).not.toContain("方案匹配度");
  });

  it("公开 token 路由位于鉴权布局之外", () => {
    const routes = readFileSync(
      new URL("../router/index.tsx", import.meta.url),
      "utf-8",
    );
    const shareRoute = routes.indexOf('path: "/share/:token"');
    const authenticatedLayout = routes.indexOf('path: "/"');

    expect(shareRoute).toBeGreaterThan(0);
    expect(shareRoute).toBeLessThan(authenticatedLayout);
  });
});
