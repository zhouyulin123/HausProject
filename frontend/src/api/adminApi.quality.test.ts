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
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({
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
      verification_status: "verified",
      taxonomy_version: "taxonomy-1",
      data_version: "data-1",
      candidate_version: "candidate-1",
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
});
