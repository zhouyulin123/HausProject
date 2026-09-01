import { describe, expect, it } from "vitest";
import {
  HOME_EXPERIENCE_STEPS,
  getHomeExperienceStep,
} from "./homeExperience";

describe("homeExperience", () => {
  it("按 AI 家装闭环提供四个连续阶段", () => {
    expect(HOME_EXPERIENCE_STEPS.map((step) => step.id)).toEqual([
      "scan",
      "understand",
      "compose",
      "deliver",
    ]);
  });

  it("超出范围时安全回到首个阶段", () => {
    expect(getHomeExperienceStep(-1)).toBe(HOME_EXPERIENCE_STEPS[0]);
    expect(getHomeExperienceStep(HOME_EXPERIENCE_STEPS.length)).toBe(
      HOME_EXPERIENCE_STEPS[0],
    );
  });

  it("每个阶段都有可展示的指标与空间标注", () => {
    for (const step of HOME_EXPERIENCE_STEPS) {
      expect(step.metric.value.length).toBeGreaterThan(0);
      expect(step.annotations.length).toBeGreaterThanOrEqual(2);
    }
  });
});
