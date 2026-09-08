import type { QualitySummary, QualityWindowDays } from "@/types/quality";
import type { UserRole } from "@/api/authApi";

export const ADMIN_QUALITY_PATH = "/admin/quality";
export const QUALITY_WINDOWS: readonly QualityWindowDays[] = [7, 30, 90];

export function canAccessQualityDashboard(role: UserRole | undefined): boolean {
  return role === "admin";
}

export function formatRate(value: number | null): string {
  return value === null ? "--" : `${(value * 100).toFixed(1)}%`;
}

export function formatDuration(value: number | null): string {
  if (value === null) return "--";
  if (value < 1_000) return `${Math.round(value)} 毫秒`;
  return `${(value / 1_000).toFixed(2)} 秒`;
}

export function hasQualitySamples(summary: QualitySummary): boolean {
  return (
    summary.generation.total > 0 ||
    summary.agent.turn_total > 0 ||
    summary.layout.total > 0 ||
    summary.feedback.total > 0 ||
    summary.feedback.glb_load_failure_total > 0 ||
    summary.effect_render.total > 0 ||
    summary.blender_render.total > 0
  );
}

export function buildFailureCodeRows(codes: Record<string, number>) {
  return Object.entries(codes)
    .map(([code, count]) => ({ code, count }))
    .sort((left, right) => right.count - left.count || left.code.localeCompare(right.code));
}
