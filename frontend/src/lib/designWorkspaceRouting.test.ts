import { describe, expect, it } from "vitest";
import {
  DESIGN_START_PATH,
  LEGACY_DESIGN_PATHS,
  parseDesignProjectId,
  WORKSPACE_CATALOG_OPTIONS,
  isFullScreenDesignPath,
} from "./designWorkspaceRouting";

describe("统一设计工作台路由", () => {
  it("整屋户型与家装编辑使用全屏工作区，普通页面保留页脚", () => {
    expect(isFullScreenDesignPath('/design/42/space')).toBe(true);
    expect(isFullScreenDesignPath('/design/42/home-design/')).toBe(true);
    expect(isFullScreenDesignPath('/design/new')).toBe(false);
    expect(isFullScreenDesignPath('/design/42')).toBe(false);
    expect(isFullScreenDesignPath('/design/42/home-design/other')).toBe(false);
  });
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
