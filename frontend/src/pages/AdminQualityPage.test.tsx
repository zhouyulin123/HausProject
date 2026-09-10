import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  GovernanceCaseTable,
  FailureTriageImportControl,
  FailureVerificationImportControl,
  FailureTriageContent,
  QualitySummaryContent,
  RealWorldReadinessContent,
  failureTriageImportErrorMessage,
  failureVerificationImportErrorMessage,
  createStableImportAttempt,
  executeImportAttempt,
  submitGovernanceMutation,
} from "./AdminQualityPage";
import { AdminApiError, type RealWorldReadiness } from "@/api/adminApi";
import type { FailureClusterListResponse } from "@/types/quality";
import type { QualitySummary } from "@/types/quality";
import type { GovernanceCase } from "@/types/admin";

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
    expect(html).toContain("用户反馈回流");
    expect(html).toContain("采用");
    expect(html).toContain(">10<");
    expect(html).toContain("删除");
    expect(html).toContain("替换");
    expect(html).toContain("移动");
    expect(html).toContain("最终选择");
    expect(html).toContain("37.5%");
    expect(html).toContain("4.25 / 5");
  });

  it("反馈零分母显示缺少样本，而不是 0% 的错误结论", () => {
    const html = renderToStaticMarkup(
      <QualitySummaryContent
        summary={{
          ...summary,
          feedback: {
            total: 0,
            action_counts: { adopt: 0, remove: 0, replace: 0, move: 0, final_select: 0 },
            modification_total: 0,
            modification_rate: null,
            final_select_total: 0,
            satisfaction_count: 0,
            satisfaction_mean: null,
            glb_load_failure_total: 0,
          },
        }}
      />,
    );
    expect(html).toContain("修改率");
    expect(html).toContain("满意度");
    expect(html).toContain("--");
    expect(html).not.toContain("0.0%");
    expect(html).not.toContain("0 / 5");
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
          record_version: 1,
          occurrence_count: 4,
          affected_count: 3,
          first_seen_at: "2026-09-01T08:00:00Z",
          last_seen_at: "2026-09-02T08:00:00Z",
          detected_version: "candidate-1",
          fixed_version: null,
          verified_version: null,
          verification_report_id: null,
          report_digest: null,
          coverage_digest: null,
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
          record_version: 2,
          occurrence_count: 3,
          affected_count: 2,
          first_seen_at: "2026-09-01T08:00:00Z",
          last_seen_at: "2026-09-02T08:00:00Z",
          detected_version: "candidate-1",
          fixed_version: null,
          verified_version: null,
          verification_report_id: null,
          report_digest: null,
          coverage_digest: null,
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
          record_version: 3,
          occurrence_count: 2,
          affected_count: 2,
          first_seen_at: "2026-09-01T08:00:00Z",
          last_seen_at: "2026-09-02T08:00:00Z",
          detected_version: "candidate-1",
          fixed_version: "prompt-2",
          verified_version: null,
          verification_report_id: null,
          report_digest: null,
          coverage_digest: null,
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
    expect(html).toContain("等待受控回归证据验证");
    expect(html).not.toContain("回归复测版本");
    expect(html).not.toContain(">验证关闭<");
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

  it("真实案例就绪度展示 20 例门槛、三组准入数和主要阻断项", () => {
    const readiness: RealWorldReadiness = {
      manifest_version: "1.0",
      dataset_id: "private-real-2026-q3",
      total: 4,
      eligible_total: 0,
      private_real_eligible_total: 0,
      blocked_total: 4,
      split_counts: {
        development: { total: 2, eligible: 0 },
        regression: { total: 1, eligible: 0 },
        blind: { total: 1, eligible: 0 },
      },
      consent_status_counts: { pending: 4 },
      annotation_status_counts: { pending: 4 },
      blocker_counts: {
        consent_not_granted: 4,
        annotation_not_ready: 4,
      },
      minimum_required: 20,
      minimum_met: false,
      checked_at: "2026-09-08T12:00:00Z",
    };
    const html = renderToStaticMarkup(
      <RealWorldReadinessContent
        data={readiness}
        loading={false}
        error=""
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain("真实案例就绪度");
    expect(html).toContain("0 / 20");
    expect(html).toContain("尚缺 20 例");
    expect(html).toContain("开发集");
    expect(html).toContain("回归集");
    expect(html).toContain("盲测集");
    expect(html).toContain("未取得授权");
    expect(html).toContain("人工标注未就绪");
    expect(html).not.toContain("case_id");
    expect(html).not.toContain("private-real-2026-q3");
  });

  it("真实案例就绪度加载失败时只显示错误和重试，不伪造零值", () => {
    const html = renderToStaticMarkup(
      <RealWorldReadinessContent
        data={null}
        loading={false}
        error="真实案例就绪度加载失败"
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain("真实案例就绪度加载失败");
    expect(html).toContain("重试");
    expect(html).not.toContain("0 / 20");
    expect(html).not.toContain("开发集 0");
  });

  it("失败分诊区提供仅接受 JSON 的本地导入命令且不显示报告内容", () => {
    const html = renderToStaticMarkup(
      <FailureTriageImportControl
        importing={false}
        error=""
        success=""
        onFile={() => undefined}
      />,
    );
    expect(html).toContain("导入签名报告");
    expect(html).toContain('accept="application/json,.json"');
    expect(html).not.toContain("report-001");
    expect(html).not.toContain("case_id");
  });

  it("失败分诊导入区显示解析、验签和冲突错误语义", () => {
    expect(failureTriageImportErrorMessage(new Error("报告 JSON 解析失败")))
      .toBe("报告 JSON 解析失败，请选择有效的 JSON 文件");
    expect(failureTriageImportErrorMessage(new AdminApiError(
      "失败分诊报告签名无效",
      422,
    ))).toBe("报告验签失败，未导入任何数据");
    expect(failureTriageImportErrorMessage(new AdminApiError(
      "report_id 已用于不同报告",
      409,
    ))).toBe("报告与已导入记录冲突，请核对报告版本和签名");
  });

  it("复测区提供仅接受 JSON 的导入命令且不显示证明内容", () => {
    const html = renderToStaticMarkup(
      <FailureVerificationImportControl
        importing={false}
        error=""
        success=""
        onFile={() => undefined}
      />,
    );

    expect(html).toContain("导入签名复测证明");
    expect(html).toContain('accept="application/json,.json"');
    expect(html).not.toContain("verification-001");
    expect(html).not.toContain("case_id");
    expect(html).not.toContain("fingerprint");
    expect(html).not.toContain("signature");
  });

  it("复测导入区区分解析、验签、冲突与服务未配置", () => {
    expect(failureVerificationImportErrorMessage(new Error("复测证明 JSON 解析失败")))
      .toBe("复测证明 JSON 解析失败，请选择有效的 JSON 文件");
    expect(failureVerificationImportErrorMessage(new AdminApiError("签名无效", 422)))
      .toBe("复测证明验签失败，未更新任何失败簇");
    expect(failureVerificationImportErrorMessage(new AdminApiError("内容冲突", 409)))
      .toBe("复测证明与已导入记录冲突，请核对证明版本");
    expect(failureVerificationImportErrorMessage(new AdminApiError("未配置", 503)))
      .toBe("服务端复测证明验签尚未配置，未更新失败簇");
  });

  it("治理收件箱只展示匿名公开状态，不渲染敏感字段", () => {
    const item = {
      case_ref: "rwc_public_001",
      origin: "private_real",
      split: "unassigned",
      redaction_review: "pending",
      consent_status: "pending",
      annotation_status: "pending",
      record_version: 4,
      blockers: ["consent_not_granted", "annotation_not_ready"],
      created_at: "2026-09-10T08:00:00Z",
      updated_at: "2026-09-10T08:00:00Z",
      task_id: 7201,
      image_id: 7301,
      asset_path: "D:/private/customer-room.png",
      asset_digest: `sha256:${"a".repeat(64)}`,
      task_input: "private user prompt",
      annotation: "private annotation content",
      evidence: "private consent evidence",
    } as unknown as GovernanceCase;

    const html = renderToStaticMarkup(
      <GovernanceCaseTable
        cases={[item]}
        selectedRefs={new Set()}
        activeCaseRef={null}
        busyCaseRef={null}
        onSelect={() => undefined}
        onActivate={() => undefined}
        onPatch={() => undefined}
      />,
    );

    expect(html).toContain("rwc_public_001");
    expect(html).toContain("r4");
    expect(html).toContain("未取得授权");
    expect(html).toContain("人工标注未就绪");
    for (const secret of [
      "7201", "7301", "customer-room.png", "sha256:",
      "private user prompt", "private annotation content", "private consent evidence",
    ]) {
      expect(html).not.toContain(secret);
    }
  });

  it("导入重试复用同一个 client_import_id，失败不返回成功结果", async () => {
    const attempt = createStableImportAttempt(7201, 7301, "stable-nonce");
    const importer = vi.fn()
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce({ created: true, case: { case_ref: "rwc_1" } });

    const first = await executeImportAttempt(attempt, importer);
    const second = await executeImportAttempt(attempt, importer);

    expect(first.outcome).toBe("error");
    expect("result" in first).toBe(false);
    expect(second.outcome).toBe("success");
    expect(importer.mock.calls).toEqual([[attempt], [attempt]]);
    expect(attempt.client_import_id).toBe("case-import-7201-7301-stable-nonce");
  });

  it("治理 CAS 冲突只刷新权威列表且绝不自动重放", async () => {
    const mutate = vi.fn().mockRejectedValue(new AdminApiError("版本冲突", 409));
    const refresh = vi.fn().mockResolvedValue(undefined);
    const mutation = {
      caseRef: "rwc_public_001",
      payload: { expected_version: 4, split: "regression" as const },
    };

    const result = await submitGovernanceMutation(mutation, mutate, refresh);

    expect(result.outcome).toBe("conflict");
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate).toHaveBeenCalledWith(mutation.caseRef, mutation.payload);
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
