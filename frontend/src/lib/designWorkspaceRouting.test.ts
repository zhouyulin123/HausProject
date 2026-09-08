import { describe, expect, it } from "vitest";
import {
  DESIGN_START_PATH,
  LEGACY_DESIGN_PATHS,
  parseDesignProjectId,
  WORKSPACE_CATALOG_OPTIONS,
} from "./designWorkspaceRouting";

describe("统一设计工作台路由", () => {
  it("入口路径稳定且只接受正整数 DesignTask 编号", () => {
    expect(DESIGN_START_PATH).toBe("/design/new");
    expect(LEGACY_DESIGN_PATHS).toEqual([
      "customize",
      "upload",
      "chat",
      "results",
    ]);
    expect(parseDesignProjectId("42")).toBe(42);
    expect(parseDesignProjectId("draft-42")).toBeNull();
    expect(parseDesignProjectId("0")).toBeNull();
    expect(parseDesignProjectId(undefined)).toBeNull();
  });

  it("工作台商品库禁止静默回退到演示数据", () => {
    expect(WORKSPACE_CATALOG_OPTIONS).toEqual({ fallbackToMock: false });
  });
});
