import { describe, expect, it } from "vitest";
import { getFurnitureDataOriginLabel } from "./furnitureDataOrigin";

describe("商品数据来源标签", () => {
  it("不会把草稿和公开参考标成已核验商品", () => {
    expect(getFurnitureDataOriginLabel("development_fixture")).toBe("开发样本（模拟业务数据）");
    expect(getFurnitureDataOriginLabel("merchant_draft")).toBe("商家草稿");
    expect(getFurnitureDataOriginLabel("merchant")).toBe("商家提供");
    expect(getFurnitureDataOriginLabel("public_reference")).toBe("公开参考");
    expect(getFurnitureDataOriginLabel("verified")).toBe("已核验");
    expect(getFurnitureDataOriginLabel("unknown")).toBe("未知来源");
  });
});
