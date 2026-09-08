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

function eventKey(event: AgentExecutionEvent): string {
  return event.event_id !== undefined
    ? `id:${event.event_id}`
    : [
        "legacy",
        event.turn_id ?? "unknown-turn",
        event.sequence,
        event.type,
        event.node,
        event.created_at ?? "unknown-time",
      ].join(":");
}

function eventOrder(event: AgentExecutionEvent): [number, string, number] {
  return [
    event.event_id ?? Number.MAX_SAFE_INTEGER,
    event.created_at ?? "",
    event.sequence,
  ];
}

export function mergeAgentExecutionEvents(
  current: AgentExecutionEvent[],
  incoming: AgentExecutionEvent[],
  limit = 50,
): AgentExecutionEvent[] {
  const boundedLimit = Math.max(1, Math.min(limit, 100));
  const merged = new Map<string, AgentExecutionEvent>();
  for (const event of current) merged.set(eventKey(event), event);
  for (const event of incoming) merged.set(eventKey(event), event);
  return [...merged.values()]
    .sort((left, right) => {
      const leftOrder = eventOrder(left);
      const rightOrder = eventOrder(right);
      return leftOrder[0] - rightOrder[0]
        || leftOrder[1].localeCompare(rightOrder[1])
        || leftOrder[2] - rightOrder[2];
    })
    .slice(-boundedLimit);
}
