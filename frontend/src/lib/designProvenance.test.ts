import { describe, expect, it } from "vitest";

import { getDesignSourceLabel } from "./designProvenance";

describe("方案来源展示", () => {
  it.each([
    ["llm", "AI 模型生成"],
    ["template", "系统模板生成"],
    ["agent", "AI 智能体编辑"],
    ["refine", "AI 智能体精修"],
    ["workspace_edit", "用户编辑版本"],
    ["demo", "Demo 演示数据"],
  ])("将 %s 映射为稳定标签", (source, expected) => {
    expect(getDesignSourceLabel(source)).toBe(expected);
  });

  it.each([undefined, "", "deepseek", "test"])(
    "未知来源 %s 不做客户端推测",
    (source) => {
      expect(getDesignSourceLabel(source)).toBe("来源未知");
    },
  );
});
