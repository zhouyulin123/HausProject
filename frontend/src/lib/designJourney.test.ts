import { describe, expect, it } from "vitest";
import { DESIGN_JOURNEY, getJourneyStage } from "./designJourney";

describe("designJourney", () => {
  it("覆盖从需求定义到方案生成的四个连续页面", () => {
    expect(DESIGN_JOURNEY.map((stage) => stage.path)).toEqual([
      "/customize",
      "/upload",
      "/chat",
      "/results",
    ]);
  });

  it("每个阶段包含递增进度和稳定编号", () => {
    expect(DESIGN_JOURNEY.map((stage) => stage.progress)).toEqual([
      25, 50, 75, 100,
    ]);
    expect(DESIGN_JOURNEY.map((stage) => stage.index)).toEqual([
      "01", "02", "03", "04",
    ]);
  });

  it("未知路径安全回退到第一阶段", () => {
    expect(getJourneyStage("/not-found")).toBe(DESIGN_JOURNEY[0]);
  });
});
