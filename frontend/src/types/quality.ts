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
