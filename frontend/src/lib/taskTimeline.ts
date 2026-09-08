import type { TaskTimelineResponse } from "@/api/designApi";

export function mergeTaskTimelinePages(
  current: TaskTimelineResponse | null,
  incoming: TaskTimelineResponse,
): TaskTimelineResponse {
  if (!current || current.task_id !== incoming.task_id) return incoming;
  const events = new Map(current.events.map((event) => [event.event_id, event]));
  for (const event of incoming.events) events.set(event.event_id, event);
  return {
    ...incoming,
    events: [...events.values()].sort((left, right) => left.event_id - right.event_id),
  };
}
