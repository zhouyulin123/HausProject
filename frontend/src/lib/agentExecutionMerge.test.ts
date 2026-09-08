import { describe, expect, it } from "vitest";
import type { AgentExecutionEvent } from "@/types/agent";
import { mergeAgentExecutionEvents } from "./agentExecution";

const event = (
  eventId: number,
  turnId: number,
  sequence: number,
  summary: string,
): AgentExecutionEvent => ({
  event_id: eventId,
  turn_id: turnId,
  sequence,
  type: "tool_completed",
  node: "catalog_search",
  status: "completed",
  source: "deterministic",
  summary,
  details: {},
  created_at: `2026-09-08T08:0${sequence}:00Z`,
});

describe("Agent 跨设备事件合并", () => {
  it("按服务端事件 ID 排序去重并限制最近记录数量", () => {
    const merged = mergeAgentExecutionEvents(
      [event(2, 1, 2, "本地旧记录"), event(4, 2, 2, "本地最新记录")],
      [event(1, 1, 1, "服务端首条"), event(2, 1, 2, "服务端可信记录"), event(3, 2, 1, "服务端第三条")],
      3,
    );

    expect(merged.map((item) => item.event_id)).toEqual([2, 3, 4]);
    expect(merged[0]?.summary).toBe("服务端可信记录");
  });

  it("兼容即时 turn 中没有数据库 ID 的事件且不混淆不同轮次", () => {
    const withoutId: AgentExecutionEvent = {
      sequence: 1,
      type: "state_changed",
      node: "done",
      status: "completed",
      source: "orchestrator",
      summary: "完成",
      details: {},
      created_at: "2026-09-08T08:10:00Z",
    };

    expect(mergeAgentExecutionEvents([withoutId], [withoutId], 10)).toHaveLength(1);
  });
});
