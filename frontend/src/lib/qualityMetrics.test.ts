import { describe, expect, it } from "vitest";
import {
  ADMIN_QUALITY_PATH,
  QUALITY_WINDOWS,
  buildFailureCodeRows,
  canAccessQualityDashboard,
  formatDuration,
  formatRate,
  hasQualitySamples,
} from "./qualityMetrics";
import type { QualitySummary } from "@/types/quality";

const emptySummary: QualitySummary = {
  generated_at: "2026-09-02T08:00:00+00:00",
  window_days: 30,
  generation: {
    total: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
    active: 0,
    success_rate: null,
    fallback_rate: null,
    duration_p50_ms: null,
    duration_p95_ms: null,
    total_tokens: 0,
    total_cost_cny: 0,
  },
  agent: { turn_total: 0, handoff_total: 0, handoff_rate: null, statuses: {} },
  layout: {
    total: 0,
    hard_pass_total: 0,
    hard_pass_rate: null,
    average_score: null,
    issue_codes: {},
  },
  feedback: {
    total: 0,
    action_counts: {
      adopt: 0,
      remove: 0,
      replace: 0,
      move: 0,
      final_select: 0,
    },
    modification_total: 0,
    modification_rate: null,
    final_select_total: 0,
    satisfaction_count: 0,
    satisfaction_mean: null,
    glb_load_failure_total: 0,
  },
  failure_codes: {},
};

describe("运营质量看板映射", () => {
  it("只开放经过约束的时间窗口和厂家后台路径", () => {
    expect(QUALITY_WINDOWS).toEqual([7, 30, 90]);
    expect(ADMIN_QUALITY_PATH).toBe("/admin/quality");
  });

  it("质量看板只允许管理员访问", () => {
    expect(canAccessQualityDashboard("admin")).toBe(true);
    expect(canAccessQualityDashboard("factory")).toBe(false);
    expect(canAccessQualityDashboard("customer")).toBe(false);
  });

  it("缺样本时不伪造百分比或延迟", () => {
    expect(formatRate(null)).toBe("--");
    expect(formatDuration(null)).toBe("--");
    expect(hasQualitySamples(emptySummary)).toBe(false);
  });

  it("格式化有效指标并按数量降序排列失败码", () => {
    expect(formatRate(0.937)).toBe("93.7%");
    expect(formatDuration(2_450)).toBe("2.45 秒");
    expect(buildFailureCodeRows({ collision: 2, invalid_quote: 5 })).toEqual([
      { code: "invalid_quote", count: 5 },
      { code: "collision", count: 2 },
    ]);
    expect(
      hasQualitySamples({
        ...emptySummary,
        agent: { ...emptySummary.agent, turn_total: 1 },
      }),
    ).toBe(true);
  });

  it("只有 GLB 加载失败样本时也显示质量看板", () => {
    expect(
      hasQualitySamples({
        ...emptySummary,
        feedback: {
          ...emptySummary.feedback,
          glb_load_failure_total: 1,
        },
      }),
    ).toBe(true);
  });
});
