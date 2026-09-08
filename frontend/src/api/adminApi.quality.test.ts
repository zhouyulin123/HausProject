import { afterEach, describe, expect, it, vi } from "vitest";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("运营质量汇总 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("只通过 window_days 请求聚合指标", async () => {
    const summary = {
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
      failure_codes: {},
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(summary));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchQualitySummary } = await import("./adminApi");
    await expect(fetchQualitySummary(30)).resolves.toEqual(summary);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/quality/summary?window_days=30",
      expect.any(Object),
    );
  });

  it("使用管理员失败簇资源完成列表、同步和状态更新", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () =>
      jsonResponse({
        items: [],
        summary: { total: 0, by_status: {}, by_severity: {} },
      }));
    vi.stubGlobal("fetch", fetchMock);
    const {
      fetchFailureClusters,
      syncFailureTriageReport,
      updateFailureCluster,
    } = await import("./adminApi");

    await fetchFailureClusters();
    await syncFailureTriageReport({
      schema_version: "1.0",
      report_id: "report-001",
      taxonomy_version: "taxonomy-1",
      data_version: "data-1",
      candidate_version: "candidate-1",
      signature_algorithm: "hmac-sha256",
      signature_key_id: "eval-key-v1",
      signature: "a".repeat(64),
      generated_at: "2026-09-02T08:00:00Z",
      failures: [],
    });
    await updateFailureCluster(9, {
      status: "in_progress",
      owner: "quality-admin",
    });

    expect(fetchMock.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/admin/quality/failure-clusters",
      "/api/admin/quality/failure-clusters/sync",
      "/api/admin/quality/failure-clusters/9",
    ]);
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: "POST" });
    expect(fetchMock.mock.calls[2]?.[1]).toMatchObject({ method: "PATCH" });
  });

  it("通过管理员资源读取真实案例就绪度聚合", async () => {
    const readiness = {
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
      blocker_counts: { consent_not_granted: 4, annotation_not_ready: 4 },
      minimum_required: 20,
      minimum_met: false,
      checked_at: "2026-09-08T12:00:00Z",
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(readiness));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchRealWorldReadiness } = await import("./adminApi");
    await expect(fetchRealWorldReadiness()).resolves.toEqual(readiness);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/quality/real-world-readiness",
      expect.any(Object),
    );
  });
});
