import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { QualitySummaryContent } from "./AdminQualityPage";
import type { QualitySummary } from "@/types/quality";

const summary: QualitySummary = {
  generated_at: "2026-09-02T08:00:00+00:00",
  window_days: 30,
  generation: {
    total: 120,
    completed: 102,
    failed: 12,
    cancelled: 3,
    active: 3,
    success_rate: 0.8947,
    fallback_rate: 0.0784,
    duration_p50_ms: 2450,
    duration_p95_ms: 9120,
    total_tokens: 987654,
    total_cost_cny: 128.46,
  },
  agent: {
    turn_total: 486,
    handoff_total: 39,
    handoff_rate: 0.0802,
    statuses: { completed: 401, needs_human: 39 },
  },
  layout: {
    total: 96,
    hard_pass_total: 89,
    hard_pass_rate: 0.9271,
    average_score: 84.6,
    issue_codes: { item_collision: 4 },
  },
  failure_codes: { invalid_quote: 7, tool_failed: 5 },
};

describe("运营质量看板内容", () => {
  it("展示有效聚合指标和失败码", () => {
    const html = renderToStaticMarkup(<QualitySummaryContent summary={summary} />);

    expect(html).toContain("89.5%");
    expect(html).toContain("P95 9.12 秒");
    expect(html).toContain("128.46");
    expect(html).toContain("invalid_quote");
    expect(html).toContain(">7<");
  });
});
