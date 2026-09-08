export interface AgentPendingQuestion {
  field: string;
  prompt: string;
  reason: string;
}

export interface AgentSceneReference {
  scene_id: number;
  version: number;
}

export interface AgentExecutionEvent {
  sequence: number;
  type:
    | "state_changed"
    | "question_created"
    | "tool_started"
    | "tool_completed"
    | "validation_failed"
    | "scene_committed"
    | "generation_queued"
    | "fallback_used"
    | "human_handoff"
    | "failed";
  node: string;
  status: string;
  source: string;
  summary: string;
  details: Record<string, unknown>;
  created_at: string | null;
}

export interface AgentExecutionState {
  currentNode: string;
  stepCount: number;
  retryCount: number;
  maxSteps: number;
  maxRetries: number;
  hardErrors: string[];
  costCny: number | null;
  costReservedCny: number;
  costLimitCny: number | null;
  executionDeadlineAt: string | null;
  cancelRequestedAt: string | null;
  turnExecutionDeadlineAt: string | null;
  events: AgentExecutionEvent[];
}

export type AgentExitReason =
  | "goal_completed"
  | "missing_facts"
  | "invalid_facts"
  | "approval_required"
  | "timeout"
  | "retry_exhausted"
  | "safety_blocked"
  | "tool_failed"
  | "generation_queued"
  | "generation_failed"
  | "cancelled";
