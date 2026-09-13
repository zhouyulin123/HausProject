import { afterEach, describe, expect, it, vi } from "vitest";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const validFailureReport = {
  schema_version: "2.0" as const,
  report_id: "report-001",
  taxonomy_version: "taxonomy-1",
  data_version: "data-1",
  manifest_digest: `sha256:${"1".repeat(64)}`,
  evidence_digest: `sha256:${"2".repeat(64)}`,
  output_digests: [`sha256:${"3".repeat(64)}`],
  candidate_version: "candidate-1",
  signature_algorithm: "hmac-sha256" as const,
  signature_key_id: "eval-key-v1",
  signature: "a".repeat(64),
  generated_at: "2026-09-02T08:00:00Z",
  failures: [{
    failure_type: "quote",
    code: "quote_mismatch",
    severity: "critical" as const,
    occurrence_count: 2,
    affected_count: 1,
  }],
};

const validFailureVerificationReport = {
  schema_version: "1.0" as const,
  report_type: "failure_verification" as const,
  report_id: "verification-001",
  taxonomy_version: "taxonomy-1",
  data_version: "data-1",
  candidate_version: "candidate-2",
  release_gate_report_digest: `sha256:${"0".repeat(64)}`,
  manifest_digests: [1, 2, 3].map((value) => `sha256:${String(value).repeat(64)}`),
  evidence_digests: [4, 5, 6].map((value) => `sha256:${String(value).repeat(64)}`),
  baseline_evidence_digests: [7, 8, 9].map((value) => `sha256:${String(value).repeat(64)}`),
  output_digests: [`sha256:${"a".repeat(64)}`],
  covered_splits: ["blind", "development", "regression"] as const,
  verified_clusters: [{
    fingerprint: "b".repeat(64),
    fixed_version: "candidate-2",
  }],
  signature_algorithm: "hmac-sha256" as const,
  signature_key_id: "eval-report-v1",
  generated_at: "2026-09-08T12:00:00Z",
  signature: "c".repeat(64),
};

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
      schema_version: "2.0",
      report_id: "report-001",
      taxonomy_version: "taxonomy-1",
      data_version: "data-1",
      manifest_digest: `sha256:${"1".repeat(64)}`,
      evidence_digest: `sha256:${"2".repeat(64)}`,
      output_digests: [`sha256:${"3".repeat(64)}`],
      candidate_version: "candidate-1",
      signature_algorithm: "hmac-sha256",
      signature_key_id: "eval-key-v1",
      signature: "a".repeat(64),
      generated_at: "2026-09-02T08:00:00Z",
      failures: [],
    });
    await updateFailureCluster(9, {
      expected_version: 3,
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
      source: "governance_database",
      frozen_dataset_count: 0,
      manifest_version: null,
      dataset_id: null,
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

  it("只解析并同步用户选择的签名 JSON 报告", async () => {
    const response = { imported: true, cluster_count: 1, clusters: [] };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(response));
    vi.stubGlobal("fetch", fetchMock);

    const { importFailureTriageReportFile } = await import("./adminApi");
    const file = new File([JSON.stringify(validFailureReport)], "triage.json", {
      type: "application/json",
    });
    await expect(importFailureTriageReportFile(file)).resolves.toEqual(response);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/admin/quality/failure-clusters/sync",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual(validFailureReport);
  });

  it("在本地拒绝损坏 JSON 和缺少签名的报告，不发起请求", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const { importFailureTriageReportFile } = await import("./adminApi");

    await expect(importFailureTriageReportFile(
      new File(["{bad"], "broken.json", { type: "application/json" }),
    )).rejects.toThrow("报告 JSON 解析失败");
    await expect(importFailureTriageReportFile(
      new File([JSON.stringify({ ...validFailureReport, signature: "" })], "unsigned.json"),
    )).rejects.toThrow("报告格式无效或缺少签名字段");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("保留验签与冲突响应状态供页面给出明确提示", async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ detail: "失败分诊报告签名无效" }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify({ detail: "report_id 已用于不同报告" }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ));
    vi.stubGlobal("fetch", fetchMock);
    const { AdminApiError, syncFailureTriageReport } = await import("./adminApi");

    await expect(syncFailureTriageReport(validFailureReport)).rejects.toEqual(
      expect.objectContaining({ status: 422, message: "失败分诊报告签名无效" }),
    );
    await expect(syncFailureTriageReport(validFailureReport)).rejects.toBeInstanceOf(AdminApiError);
  });

  it("只解析复测证明并调用管理员 verify 端点", async () => {
    const response = {
      imported: true,
      cluster_count: 1,
      report_digest: `sha256:${"d".repeat(64)}`,
      coverage_digest: `sha256:${"e".repeat(64)}`,
      clusters: [],
    };
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(response));
    vi.stubGlobal("fetch", fetchMock);
    const { importFailureVerificationReportFile } = await import("./adminApi");

    await expect(importFailureVerificationReportFile(new File(
      [JSON.stringify(validFailureVerificationReport)],
      "verification.json",
      { type: "application/json" },
    ))).resolves.toEqual(response);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/admin/quality/failure-clusters/verify",
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)))
      .toEqual(validFailureVerificationReport);
  });

  it.each([
    ["split 摘要不足", { manifest_digests: validFailureVerificationReport.manifest_digests.slice(0, 2) }],
    ["split 顺序错误", { covered_splits: ["development", "regression", "blind"] }],
    ["摘要未排序去重", { evidence_digests: [
      validFailureVerificationReport.evidence_digests[1],
      validFailureVerificationReport.evidence_digests[0],
      validFailureVerificationReport.evidence_digests[1],
    ] }],
    ["失败簇为空", { verified_clusters: [] }],
    ["失败簇指纹重复", { verified_clusters: [
      validFailureVerificationReport.verified_clusters[0],
      validFailureVerificationReport.verified_clusters[0],
    ] }],
    ["包含额外隐私字段", { case_id: "private-case" }],
  ])("本地拒绝%s的复测证明且不请求服务端", async (_label, override) => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const { importFailureVerificationReportFile } = await import("./adminApi");
    const report = { ...validFailureVerificationReport, ...override };

    await expect(importFailureVerificationReportFile(new File(
      [JSON.stringify(report)], "verification.json", { type: "application/json" },
    ))).rejects.toThrow("复测证明格式无效或缺少签名字段");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("限制复测证明为 JSON 且不超过 1 MB", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const { importFailureVerificationReportFile } = await import("./adminApi");

    await expect(importFailureVerificationReportFile(
      new File(["{bad"], "verification.json", { type: "application/json" }),
    )).rejects.toThrow("复测证明 JSON 解析失败");
    await expect(importFailureVerificationReportFile(
      new File(["{}"], "verification.txt"),
    )).rejects.toThrow("仅支持 JSON 格式的签名复测证明");
    await expect(importFailureVerificationReportFile(
      new File(["x".repeat(1024 * 1024 + 1)], "verification.json"),
    )).rejects.toThrow("签名复测证明不能超过 1 MB");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("真实案例治理请求只提交公开 ID、CAS 与受控证据字段", async () => {
    const response = { items: [], total: 0 };
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(
      async () => jsonResponse(response),
    );
    vi.stubGlobal("fetch", fetchMock);
    const {
      createRealWorldAnnotationRevision,
      createRealWorldConsentDecision,
      fetchRealWorldCases,
      freezeRealWorldDataset,
      importRealWorldCase,
      previewRealWorldCaseImport,
      updateRealWorldCase,
    } = await import("./adminApi");
    const importPayload = {
      client_import_id: "case-import-7201-7301-stable",
      task_id: 7201,
      uploaded_image_id: 7301,
    };

    await fetchRealWorldCases();
    await previewRealWorldCaseImport(importPayload);
    await importRealWorldCase(importPayload);
    await updateRealWorldCase("rwc_public_001", {
      expected_version: 4,
      redaction_review: "reviewed",
    });
    await createRealWorldConsentDecision("rwc_public_001", {
      expected_version: 5,
      decision: "granted",
      legal_basis: "explicit_consent",
      allowed_purposes: ["offline_evaluation"],
      evidence_digest: `sha256:${"e".repeat(64)}`,
      effective_at: "2026-09-10T08:00:00Z",
      expires_at: "2027-09-10T08:00:00Z",
    });
    await createRealWorldAnnotationRevision("rwc_public_001", {
      expected_version: 6,
      annotation: { schema_version: "1.0", annotation_type: "real_world_case_annotation" },
    });
    await freezeRealWorldDataset({
      dataset_version: "dataset-2026-09-10.1",
      cases: [{ case_ref: "rwc_public_001", expected_version: 7 }],
    });

    expect(fetchMock.mock.calls.map(([path]) => String(path))).toEqual([
      "/api/admin/quality/real-world-cases",
      "/api/admin/quality/real-world-case-imports/preview",
      "/api/admin/quality/real-world-case-imports",
      "/api/admin/quality/real-world-cases/rwc_public_001",
      "/api/admin/quality/real-world-cases/rwc_public_001/consent-decisions",
      "/api/admin/quality/real-world-cases/rwc_public_001/annotation-revisions",
      "/api/admin/quality/real-world-dataset-revisions",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual(importPayload);
    expect(JSON.parse(String(fetchMock.mock.calls[3]?.[1]?.body))).toEqual({
      expected_version: 4,
      redaction_review: "reviewed",
    });
    const consentBody = JSON.parse(String(fetchMock.mock.calls[4]?.[1]?.body));
    expect(consentBody).toEqual(expect.objectContaining({
      evidence_digest: `sha256:${"e".repeat(64)}`,
      allowed_purposes: ["offline_evaluation"],
    }));
    expect(consentBody).not.toHaveProperty("evidence");
    expect(consentBody).not.toHaveProperty("actor_user_id");
  });
});
