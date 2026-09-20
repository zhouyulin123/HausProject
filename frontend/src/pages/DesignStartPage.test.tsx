import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import DesignStartPage from "./DesignStartPage";

describe("设计入口用户文案", () => {
  it("按用户目标命名三个开始按钮，不展示项目或后端术语", () => {
    const html = renderToStaticMarkup(<MemoryRouter><DesignStartPage /></MemoryRouter>);
    for (const label of ["开始搭配", "开始设计家具", "开始设计房间"]) {
      expect(html).toContain(label);
    }
    expect(html).not.toContain("建立项目");
    expect(html).not.toContain("设计任务");
    expect(html).not.toContain("design project");
  });
});
