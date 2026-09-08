import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FailureTriageContent, QualitySummaryContent } from "./AdminQualityPage";
import type { FailureClusterListResponse } from "@/types/quality";
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
    node_latency: {
      parse_requirements: { samples: 120, p50_ms: 320, p95_ms: 980 },
    },
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
  feedback: {
    total: 24,
    action_counts: {
      adopt: 10,
      remove: 3,
      replace: 2,
      move: 4,
      final_select: 5,
    },
    modification_total: 9,
    modification_rate: 0.375,
    final_select_total: 5,
    satisfaction_count: 4,
    satisfaction_mean: 4.25,
    glb_load_failure_total: 6,
  },
  effect_render: {
    total: 20, queued: 2, running: 1, completed: 15, failed: 0,
    dead_letter: 2, cancelled: 0, success_rate: 15 / 17,
    queue_wait_p50_ms: 800, queue_wait_p95_ms: 2400,
    execution_p50_ms: 12000, execution_p95_ms: 30000,
  },
  blender_render: {
    total: 10, queued: 1, running: 1, completed: 7, failed: 1,
    dead_letter: 0, cancelled: 0, success_rate: 0.875,
    queue_wait_p50_ms: 1500, queue_wait_p95_ms: 5000,
    execution_p50_ms: 18000, execution_p95_ms: 45000,
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
    expect(html).toContain("GLB 加载失败");
    expect(html).toContain(">6<");
    expect(html).toContain("效果图队列");
    expect(html).toContain("Blender 队列");
    expect(html).toContain("节点耗时");
    expect(html).toContain("parse_requirements");
  });

  it("失败簇展示严重度、状态和当前阶段的明确动作", () => {
    const clusters: FailureClusterListResponse = {
      summary: {
        total: 3,
        by_status: { open: 1, in_progress: 1, resolved: 1 },
        by_severity: { critical: 1, high: 2 },
      },
      items: [
        {
          id: 1,
          fingerprint: "a".repeat(64),
          taxonomy_version: "taxonomy-1",
          data_version: "data-1",
          failure_type: "quote",
          code: "quote_mismatch",
          severity: "critical",
          status: "open",
          owner: null,
          occurrence_count: 4,
          affected_count: 3,
          first_seen_at: "2026-09-01T08:00:00Z",
          last_seen_at: "2026-09-02T08:00:00Z",
          detected_version: "candidate-1",
          fixed_version: null,
          verified_version: null,
          created_at: "2026-09-02T08:00:00Z",
          updated_at: "2026-09-02T08:00:00Z",
        },
        {
          id: 2,
          fingerprint: "b".repeat(64),
          taxonomy_version: "taxonomy-1",
          data_version: "data-1",
          failure_type: "layout",
          code: "item_collision",
          severity: "high",
          status: "in_progress",
          owner: "quality-admin",
          occurrence_count: 3,
          affected_count: 2,
          first_seen_at: "2026-09-01T08:00:00Z",
          last_seen_at: "2026-09-02T08:00:00Z",
          detected_version: "candidate-1",
          fixed_version: null,
          verified_version: null,
          created_at: "2026-09-02T08:00:00Z",
          updated_at: "2026-09-02T08:00:00Z",
        },
        {
          id: 3,
          fingerprint: "c".repeat(64),
          taxonomy_version: "taxonomy-1",
          data_version: "data-1",
          failure_type: "requirement",
          code: "missing_budget",
          severity: "high",
          status: "resolved",
          owner: "quality-admin",
          occurrence_count: 2,
          affected_count: 2,
          first_seen_at: "2026-09-01T08:00:00Z",
          last_seen_at: "2026-09-02T08:00:00Z",
          detected_version: "candidate-1",
          fixed_version: "prompt-2",
          verified_version: null,
          created_at: "2026-09-02T08:00:00Z",
          updated_at: "2026-09-02T08:00:00Z",
        },
      ],
    };
    const html = renderToStaticMarkup(
      <FailureTriageContent
        data={clusters}
        loading={false}
        error=""
        actionError=""
        busyClusterId={null}
        onRefresh={() => undefined}
        onUpdate={() => undefined}
      />,
    );

    expect(html).toContain("失败修复闭环");
    expect(html).toContain("严重");
    expect(html).toContain("待认领");
    expect(html).toContain("认领并开始修复");
    expect(html).toContain("标记修复");
    expect(html).toContain("验证关闭");
    expect(html).not.toContain("case_id");
  });

  it("失败簇 API 错误以可见状态展示", () => {
    const html = renderToStaticMarkup(
      <FailureTriageContent
        data={null}
        loading={false}
        error="失败簇加载失败"
        actionError=""
        busyClusterId={null}
        onRefresh={() => undefined}
        onUpdate={() => undefined}
      />,
    );
    expect(html).toContain("失败簇加载失败");
    expect(html).toContain("重试加载");
  });
});
