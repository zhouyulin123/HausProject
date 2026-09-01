import { describe, expect, it } from "vitest";
import { furnitureModelKind, lampModelKind } from "@/lib/furnitureModelKind";

describe("程序化家具模型分发", () => {
  it("床头吊灯优先识别为灯具而不是床", () => {
    expect(furnitureModelKind("床头吊灯")).toBe("lamp");
    expect(furnitureModelKind("软包床")).toBe("bed");
  });

  it("按显式安装元数据区分床头吊灯与餐吊灯", () => {
    expect(
      lampModelKind({ 安装参数: { 锚点: "ceiling", 灯具模型: "pendant" } }),
    ).toBe("pendant");
    expect(
      lampModelKind({ 安装参数: { 锚点: "ceiling", 灯具模型: "ring" } }),
    ).toBe("ring");
  });
});
