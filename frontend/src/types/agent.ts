export interface AgentPendingQuestion {
  field: string;
  prompt: string;
  reason: string;
}

export interface AgentSceneReference {
  scene_id: number;
  version: number;
}

export type AgentExitReason =
  | "goal_completed"
  | "missing_facts"
  | "invalid_facts"
  | "approval_required"
  | "retry_exhausted"
  | "safety_blocked"
  | "tool_failed"
  | "generation_queued"
  | "generation_failed"
  | "cancelled";
