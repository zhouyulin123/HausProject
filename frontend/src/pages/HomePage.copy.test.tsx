import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import HomePage from "./HomePage";

describe("首页证据边界文案", () => {
  it("不把演示场景宣传为真实案例、已核验商品或真实质量指标", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(html).not.toContain("98.2%");
    expect(html).not.toContain("需求匹配");
    expect(html).not.toContain("真实案例");
    expect(html).not.toContain("真实商品");
    expect(html).not.toContain("动线优化 +18%");
    expect(html).not.toContain("采光利用 +23%");
    expect(html).toContain("空间方案");
    expect(html).toContain("目录商品");
  });
});
