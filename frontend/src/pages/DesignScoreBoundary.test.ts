import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";


describe("方案推荐分数证据边界", () => {
  it.each(["../components/design/DesignCard.tsx", "./DesignDetailPage.tsx"])(
    "%s 不展示模型自报百分比分数",
    (relativePath) => {
      const source = readFileSync(new URL(relativePath, import.meta.url), "utf-8");

      expect(source).not.toContain("plan.score");
      expect(source).not.toContain("AI 推荐指数");
    },
  );

  it("结果页不按无证据分数重排候选方案", () => {
    const source = readFileSync(new URL("./ResultsPage.tsx", import.meta.url), "utf-8");

    expect(source).not.toContain(".score");
    expect(source).not.toContain("风格最匹配");
  });

  it("方案详情页不通过 URL 静默加载 Mock 方案", () => {
    const source = readFileSync(new URL("./DesignDetailPage.tsx", import.meta.url), "utf-8");

    expect(source).not.toContain('from "@/data/mockDesigns"');
    expect(source).not.toContain("mockDesigns.find");
  });
});
