import { describe, expect, it } from "vitest";
import {
  DESIGN_START_PATH,
  parseDesignProjectId,
} from "./designWorkspaceRouting";

describe("统一设计工作台路由", () => {
  it("入口路径稳定且只接受正整数 DesignTask 编号", () => {
    expect(DESIGN_START_PATH).toBe("/design/new");
    expect(parseDesignProjectId("42")).toBe(42);
    expect(parseDesignProjectId("draft-42")).toBeNull();
    expect(parseDesignProjectId("0")).toBeNull();
    expect(parseDesignProjectId(undefined)).toBeNull();
  });
});
