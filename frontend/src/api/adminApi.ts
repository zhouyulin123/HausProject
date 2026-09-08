/**
 * 管理员 API：用户角色管理（把普通用户提升为厂家/管理员）。
 */

import { readToken } from "./authApi";
import type { AuthUser, UserRole } from "./authApi";
import { useAuthStore } from "@/store/useAuthStore";
import type {
  FailureCluster,
  FailureClusterListResponse,
  FailureClusterUpdate,
  FailureTriageReport,
  FailureTriageSyncResponse,
  QualitySummary,
  QualityWindowDays,
} from "@/types/quality";

export interface AdminUser extends AuthUser {
  created_at: string | null;
  last_login_at: string | null;
}

export type RealWorldSplit = "development" | "regression" | "blind";

export interface RealWorldReadiness {
  manifest_version: string;
  dataset_id: string;
  total: number;
  eligible_total: number;
  private_real_eligible_total: number;
  blocked_total: number;
  split_counts: Record<RealWorldSplit, {
    total: number;
    eligible: number;
  }>;
  consent_status_counts: Record<string, number>;
  annotation_status_counts: Record<string, number>;
  blocker_counts: Record<string, number>;
  minimum_required: number;
  minimum_met: boolean;
  checked_at: string;
}

export class AdminApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    if (resp.status === 401) {
      useAuthStore.getState().logout();
    }
    let message = `${path} -> ${resp.status}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      /* 保留默认 message */
    }
    throw new AdminApiError(message, resp.status);
  }
  return resp.json() as Promise<T>;
}

export async function listUsers(q?: string): Promise<AdminUser[]> {
  const query = q ? `?q=${encodeURIComponent(q)}` : "";
  const data = await adminRequest<{ users: AdminUser[] }>(`/api/admin/users${query}`);
  return data.users;
}

export async function updateUserRole(
  userId: number,
  role: UserRole,
): Promise<AdminUser> {
  const data = await adminRequest<{ user: AdminUser }>(
    `/api/admin/users/${userId}/role`,
    { method: "PATCH", body: JSON.stringify({ role }) },
  );
  return data.user;
}

export async function fetchQualitySummary(
  windowDays: QualityWindowDays,
): Promise<QualitySummary> {
  return adminRequest<QualitySummary>(
    `/api/admin/quality/summary?window_days=${windowDays}`,
  );
}

export async function fetchRealWorldReadiness(): Promise<RealWorldReadiness> {
  return adminRequest<RealWorldReadiness>(
    "/api/admin/quality/real-world-readiness",
  );
}

export async function fetchFailureClusters(): Promise<FailureClusterListResponse> {
  return adminRequest<FailureClusterListResponse>(
    "/api/admin/quality/failure-clusters",
  );
}

export async function syncFailureTriageReport(
  report: FailureTriageReport,
): Promise<FailureTriageSyncResponse> {
  return adminRequest<FailureTriageSyncResponse>(
    "/api/admin/quality/failure-clusters/sync",
    { method: "POST", body: JSON.stringify(report) },
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

const failureSeverities = new Set(["low", "medium", "high", "critical"]);
const digestPattern = /^sha256:[0-9a-f]{64}$/;
const reportKeys = new Set([
  "schema_version",
  "report_id",
  "taxonomy_version",
  "data_version",
  "manifest_digest",
  "evidence_digest",
  "output_digests",
  "candidate_version",
  "signature_algorithm",
  "signature_key_id",
  "signature",
  "generated_at",
  "failures",
]);
const failureKeys = new Set([
  "failure_type",
  "code",
  "severity",
  "occurrence_count",
  "affected_count",
]);

export function parseFailureTriageReportJson(text: string): FailureTriageReport {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("报告 JSON 解析失败");
  }
  if (!isRecord(parsed)) throw new Error("报告格式无效或缺少签名字段");

  const requiredStrings = [
    "report_id",
    "taxonomy_version",
    "data_version",
    "candidate_version",
    "signature_key_id",
    "signature",
    "generated_at",
  ];
  const failures = parsed.failures;
  const outputDigests = parsed.output_digests;
  const validFailures = Array.isArray(failures) && failures.every((failure) =>
    isRecord(failure) &&
    Object.keys(failure).every((key) => failureKeys.has(key)) &&
    Object.keys(failure).length === failureKeys.size &&
    isNonEmptyString(failure.failure_type) &&
    isNonEmptyString(failure.code) &&
    typeof failure.severity === "string" &&
    failureSeverities.has(failure.severity) &&
    Number.isInteger(failure.occurrence_count) &&
    Number(failure.occurrence_count) > 0 &&
    Number.isInteger(failure.affected_count) &&
    Number(failure.affected_count) > 0 &&
    Number(failure.affected_count) <= Number(failure.occurrence_count)
  );
  if (
    Object.keys(parsed).some((key) => !reportKeys.has(key)) ||
    Object.keys(parsed).length !== reportKeys.size ||
    parsed.schema_version !== "2.0" ||
    parsed.signature_algorithm !== "hmac-sha256" ||
    requiredStrings.some((key) => !isNonEmptyString(parsed[key])) ||
    !digestPattern.test(String(parsed.manifest_digest)) ||
    !digestPattern.test(String(parsed.evidence_digest)) ||
    !Array.isArray(outputDigests) ||
    !outputDigests.every((digest) => typeof digest === "string" && digestPattern.test(digest)) ||
    outputDigests.join("\n") !== [...new Set(outputDigests)].sort().join("\n") ||
    !/^[0-9a-fA-F]{64}$/.test(String(parsed.signature)) ||
    Number.isNaN(Date.parse(String(parsed.generated_at))) ||
    !validFailures
  ) {
    throw new Error("报告格式无效或缺少签名字段");
  }
  return parsed as unknown as FailureTriageReport;
}

const MAX_FAILURE_TRIAGE_REPORT_BYTES = 1024 * 1024;

export async function importFailureTriageReportFile(
  file: File,
): Promise<FailureTriageSyncResponse> {
  if (!file.name.toLowerCase().endsWith(".json")) {
    throw new Error("仅支持 JSON 格式的失败分诊报告");
  }
  if (file.size > MAX_FAILURE_TRIAGE_REPORT_BYTES) {
    throw new Error("失败分诊报告不能超过 1 MB");
  }
  const report = parseFailureTriageReportJson(await file.text());
  return syncFailureTriageReport(report);
}

export async function updateFailureCluster(
  clusterId: number,
  update: FailureClusterUpdate,
): Promise<FailureCluster> {
  return adminRequest<FailureCluster>(
    `/api/admin/quality/failure-clusters/${clusterId}`,
    { method: "PATCH", body: JSON.stringify(update) },
  );
}
