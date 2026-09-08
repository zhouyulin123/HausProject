import { describe, expect, it } from "vitest";
import type { TaskTimelineResponse } from "@/api/designApi";
import { mergeTaskTimelinePages } from "./taskTimeline";

const page = (ids: number[], overrides: Partial<TaskTimelineResponse> = {}): TaskTimelineResponse => ({
  task_id: 42,
  events: ids.map((eventId) => ({
    event_id: eventId,
    source_type: "agent",
    source_id: 9,
    attempt: null,
    event_code: `agent.event.${eventId}`,
    summary: `事件 ${eventId}`,
    billing_status: "not_billable",
    cost_cny: null,
    occurred_at: `2026-09-08T09:00:0${eventId}Z`,
  })),
  next_cursor: ids.at(-1) ?? null,
  next_before_id: null,
  next_after_id: null,
  known_cost_cny: null,
  has_unknown_cost: false,
  unknown_cost_event_count: 0,
  ...overrides,
});

describe("统一任务时间线分页", () => {
  it("按事件 ID 合并去重并采用最新总账", () => {
    const merged = mergeTaskTimelinePages(
      page([1, 2], { known_cost_cny: 0.5 }),
      page([2, 3], {
        next_cursor: null,
        known_cost_cny: 0.8,
        has_unknown_cost: true,
        unknown_cost_event_count: 2,
      }),
    );

    expect(merged.events.map((event) => event.event_id)).toEqual([1, 2, 3]);
    expect(merged.known_cost_cny).toBe(0.8);
    expect(merged.has_unknown_cost).toBe(true);
    expect(merged.unknown_cost_event_count).toBe(2);
    expect(merged.next_cursor).toBeNull();
  });

  it("向前加载保留增量游标，向后刷新保留旧页游标", () => {
    const current = page([10, 11], {
      next_before_id: 10,
      next_after_id: null,
    });
    const withOlder = mergeTaskTimelinePages(
      current,
      page([8, 9], { next_before_id: 8, next_after_id: null }),
      "older",
    );
    const withNewer = mergeTaskTimelinePages(
      withOlder,
      page([12], { next_before_id: null, next_after_id: null }),
      "newer",
    );

    expect(withNewer.events.map((event) => event.event_id)).toEqual([8, 9, 10, 11, 12]);
    expect(withNewer.next_before_id).toBe(8);
    expect(withNewer.next_after_id).toBeNull();
  });
});
