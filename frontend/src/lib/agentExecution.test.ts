import { describe, expect, it } from "vitest";
import type {
  AgentTurnResponse,
  DesignAgentStateResponse,
} from "@/api/designApi";
import {
  agentExecutionFromCheckpoint,
  agentExecutionFromTurn,
} from "./agentExecution";

const executionFields = {
  status: "running" as const,
  current_node: "verify_plan",
  active_room_id: "living-room",
  facts: {},
  fact_evidence: {},
  step_count: 6,
  retry_count: 1,
  max_steps: 12,
  max_retries: 2,
  pending_questions: [],
  hard_errors: ["budget_exceeded"],
  custom_furniture_spec: null,
  approval_required: false,
  exit_reason: "generation_queued" as const,
  run_id: 9,
  cost_cny: 0.48,
  cost_reserved_cny: 0.12,
  cost_limit_cny: 2,
  execution_deadline_at: "2026-09-08T08:30:00Z",
  cancel_requested_at: null,
  turn_execution_deadline_at: "2026-09-08T08:25:00Z",
};

describe("Agent 执行快照映射", () => {
  it("从 turn 响应映射全部执行字段和事件", () => {
    const response = {
      task_id: 42,
      turn_id: 3,
      state_version: 8,
      status: "running",
      active_mode: "catalog_design",
      active_room_id: "living-room",
      intent: "design",
      reply: "继续校验方案",
      state: executionFields,
      pending_questions: [],
      events: [{
        sequence: 8,
        type: "validation_failed",
        node: "verify_plan",
        status: "failed",
        source: "deterministic",
        summary: "预算超过上限",
        details: {},
        created_at: "2026-09-08T08:22:00Z",
      }],
      approval_required: false,
      scene_ref: null,
      run_id: 9,
      exit_reason: "generation_queued",
      result: null,
      open_geometry: null,
      partialCompletion: false,
    } satisfies AgentTurnResponse;

    expect(agentExecutionFromTurn(response)).toEqual({
      currentNode: "verify_plan",
      stepCount: 6,
      retryCount: 1,
      maxSteps: 12,
      maxRetries: 2,
      hardErrors: ["budget_exceeded"],
      costCny: 0.48,
      costReservedCny: 0.12,
      costLimitCny: 2,
      executionDeadlineAt: "2026-09-08T08:30:00Z",
      cancelRequestedAt: null,
      turnExecutionDeadlineAt: "2026-09-08T08:25:00Z",
      events: response.events,
    });
  });

  it("checkpoint 不含事件时保留最近的持久化工具记录", () => {
    const recentEvents = [{
      sequence: 8,
      type: "tool_completed" as const,
      node: "verify_plan",
      status: "completed",
      source: "deterministic",
      summary: "报价复算完成",
      details: {},
      created_at: null,
    }];
    const checkpoint = {
      task_id: 42,
      state_version: 9,
      confirmed_requirement: {},
      room_model: null,
      active_mode: "catalog_design",
      intent: "design",
      ...executionFields,
      status: "completed",
      custom_furniture_draft: null,
      scene_ref: null,
      result: null,
      open_geometry: null,
      messages: [],
    } satisfies DesignAgentStateResponse;

    expect(agentExecutionFromCheckpoint(checkpoint, recentEvents).events).toEqual(recentEvents);
  });
});
