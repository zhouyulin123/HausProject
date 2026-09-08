import type {
  AgentTurnResponse,
  DesignAgentStateResponse,
} from "@/api/designApi";
import type {
  AgentExecutionEvent,
  AgentExecutionState,
} from "@/types/agent";

type AgentExecutionPayload = AgentTurnResponse["state"] | DesignAgentStateResponse;

function mapExecution(
  payload: AgentExecutionPayload,
  events: AgentExecutionEvent[],
): AgentExecutionState {
  return {
    currentNode: payload.current_node,
    stepCount: payload.step_count,
    retryCount: payload.retry_count,
    maxSteps: payload.max_steps,
    maxRetries: payload.max_retries,
    hardErrors: [...payload.hard_errors],
    costCny: payload.cost_cny,
    costReservedCny: payload.cost_reserved_cny,
    costLimitCny: payload.cost_limit_cny,
    executionDeadlineAt: payload.execution_deadline_at,
    cancelRequestedAt: payload.cancel_requested_at,
    turnExecutionDeadlineAt: payload.turn_execution_deadline_at,
    events: events.map((event) => ({ ...event, details: { ...event.details } })),
  };
}

export function agentExecutionFromTurn(
  response: AgentTurnResponse,
): AgentExecutionState {
  return mapExecution(response.state, response.events);
}

export function agentExecutionFromCheckpoint(
  checkpoint: DesignAgentStateResponse,
  recentEvents: AgentExecutionEvent[] = [],
): AgentExecutionState {
  return mapExecution(checkpoint, recentEvents);
}
