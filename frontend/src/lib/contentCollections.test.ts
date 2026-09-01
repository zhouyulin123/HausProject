import { describe, expect, it } from "vitest";
import { CONTENT_COLLECTIONS, getContentCollection } from "./contentCollections";

describe("contentCollections", () => {
  it("定义案例、家具和方案三个产品档案库", () => {
    expect(CONTENT_COLLECTIONS.map((item) => item.path)).toEqual([
      "/styles",
      "/furniture",
      "/my-designs",
    ]);
  });

  it("每个档案库拥有唯一代码和非空指标", () => {
    expect(new Set(CONTENT_COLLECTIONS.map((item) => item.code)).size).toBe(3);
    expect(CONTENT_COLLECTIONS.every((item) => item.metrics.length >= 2)).toBe(true);
  });

  it("按路径返回档案定义，未知路径回退到案例库", () => {
    expect(getContentCollection("/furniture").code).toBe("MATERIAL INDEX");
    expect(getContentCollection("/missing")).toBe(CONTENT_COLLECTIONS[0]);
  });
});
