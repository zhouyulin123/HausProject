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
    throw new Error(message);
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

export async function updateFailureCluster(
  clusterId: number,
  update: FailureClusterUpdate,
): Promise<FailureCluster> {
  return adminRequest<FailureCluster>(
    `/api/admin/quality/failure-clusters/${clusterId}`,
    { method: "PATCH", body: JSON.stringify(update) },
  );
}
