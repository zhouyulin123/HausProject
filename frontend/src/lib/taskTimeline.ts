import type { TaskTimelineResponse } from "@/api/designApi";

export function mergeTaskTimelinePages(
  current: TaskTimelineResponse | null,
  incoming: TaskTimelineResponse,
  direction: "older" | "newer" = "newer",
): TaskTimelineResponse {
  if (!current || current.task_id !== incoming.task_id) return incoming;
  const events = new Map(current.events.map((event) => [event.event_id, event]));
  for (const event of incoming.events) events.set(event.event_id, event);
  return {
    ...incoming,
    events: [...events.values()].sort((left, right) => left.event_id - right.event_id),
    next_before_id:
      direction === "older" ? incoming.next_before_id : current.next_before_id,
    next_after_id:
      direction === "newer" ? incoming.next_after_id : current.next_after_id,
  };
}
