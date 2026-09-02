export type QualityWindowDays = 7 | 30 | 90;

export interface QualityGenerationMetrics {
  total: number;
  completed: number;
  failed: number;
  cancelled: number;
  active: number;
  success_rate: number | null;
  fallback_rate: number | null;
  duration_p50_ms: number | null;
  duration_p95_ms: number | null;
  total_tokens: number;
  total_cost_cny: number;
}

export interface QualityAgentMetrics {
  turn_total: number;
  handoff_total: number;
  handoff_rate: number | null;
  statuses: Record<string, number>;
}

export interface QualityLayoutMetrics {
  total: number;
  hard_pass_total: number;
  hard_pass_rate: number | null;
  average_score: number | null;
  issue_codes: Record<string, number>;
}

export interface QualitySummary {
  generated_at: string;
  window_days: number;
  generation: QualityGenerationMetrics;
  agent: QualityAgentMetrics;
  layout: QualityLayoutMetrics;
  failure_codes: Record<string, number>;
}

export type FailureSeverity = "low" | "medium" | "high" | "critical";
export type FailureStatus = "open" | "in_progress" | "resolved" | "verified";

export interface FailureCluster {
  id: number;
  fingerprint: string;
  taxonomy_version: string;
  data_version: string;
  failure_type: string;
  code: string;
  severity: FailureSeverity;
  status: FailureStatus;
  owner: string | null;
  occurrence_count: number;
  affected_count: number;
  first_seen_at: string;
  last_seen_at: string;
  detected_version: string;
  fixed_version: string | null;
  verified_version: string | null;
  created_at: string;
  updated_at: string;
}

export interface FailureClusterListResponse {
  items: FailureCluster[];
  summary: {
    total: number;
    by_status: Record<string, number>;
    by_severity: Record<string, number>;
  };
}

export interface FailureClusterUpdate {
  status?: FailureStatus;
  owner?: string | null;
  fixed_version?: string | null;
  verified_version?: string | null;
}

export interface FailureTriageReport {
  schema_version: "1.0";
  report_id: string;
  verification_status: "verified";
  taxonomy_version: string;
  data_version: string;
  candidate_version: string;
  generated_at: string;
  failures: Array<{
    failure_type: string;
    code: string;
    severity: FailureSeverity;
    occurrence_count: number;
    affected_count: number;
  }>;
}

export interface FailureTriageSyncResponse {
  imported: boolean;
  cluster_count: number;
  clusters: FailureCluster[];
}
