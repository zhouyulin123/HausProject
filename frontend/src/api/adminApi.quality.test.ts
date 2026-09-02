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
});
