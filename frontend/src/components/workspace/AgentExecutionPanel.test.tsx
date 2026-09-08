import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { AgentExecutionState } from "@/types/agent";
import AgentExecutionPanel from "./AgentExecutionPanel";

const execution: AgentExecutionState = {
  currentNode: "retrieve_catalog",
  stepCount: 4,
  retryCount: 1,
  maxSteps: 12,
  maxRetries: 2,
  hardErrors: [],
  costCny: 0.36,
  costReservedCny: 0.14,
  costLimitCny: 2,
  executionDeadlineAt: "2026-09-08T08:30:00Z",
  turnExecutionDeadlineAt: "2026-09-08T08:25:00Z",
  cancelRequestedAt: null,
  events: [
    {
      sequence: 2,
      type: "tool_started",
      node: "retrieve_catalog",
      status: "running",
      source: "catalog",
      summary: "正在查询有效商品",
      details: {},
      created_at: "2026-09-08T08:19:00Z",
    },
    {
      sequence: 3,
      type: "tool_completed",
      node: "retrieve_catalog",
      status: "completed",
      source: "catalog",
      summary: "已筛选 12 件可用商品",
      details: {},
      created_at: "2026-09-08T08:20:00Z",
    },
  ],
};

describe("Agent 执行状态区", () => {
  it("展示当前步骤、工具事件、重试、真实成本、截止时间和退出原因", () => {
    const html = renderToStaticMarkup(
      <AgentExecutionPanel
        status="running"
        exitReason="generation_queued"
        execution={execution}
      />,
    );

    expect(html).toContain("商品检索");
    expect(html).toContain("步骤 4 / 12");
    expect(html).toContain("重试 1 / 2");
    expect(html).toContain("¥0.36");
    expect(html).toContain("预留 ¥0.14");
    expect(html).toContain("上限 ¥2.00");
    expect(html).toContain("本轮截止");
    expect(html).toContain("正在查询有效商品");
    expect(html).toContain("已筛选 12 件可用商品");
    expect(html).toContain("后台生成已排队");
  });

  it("缺少实际成本和事件时不伪造金额或执行记录", () => {
    const html = renderToStaticMarkup(
      <AgentExecutionPanel
        status="waiting_user"
        exitReason="missing_facts"
        execution={{
          ...execution,
          currentNode: "request_clarification",
          costCny: null,
          costReservedCny: 0,
          costLimitCny: null,
          executionDeadlineAt: null,
          turnExecutionDeadlineAt: null,
          events: [],
        }}
      />,
    );

    expect(html).toContain("等待补充信息");
    expect(html).toContain("尚无已结算成本");
    expect(html).toContain("暂无工具执行记录");
    expect(html).not.toContain("¥0.00");
  });

  it("跨轮次相同序号的事件使用服务端事件 ID 并全部展示", () => {
    const html = renderToStaticMarkup(
      <AgentExecutionPanel
        status="running"
        exitReason={null}
        execution={{
          ...execution,
          events: [
            { ...execution.events[0]!, event_id: 21, turn_id: 7, summary: "第一轮工具" },
            { ...execution.events[0]!, event_id: 25, turn_id: 8, summary: "第二轮工具" },
          ],
        }}
      />,
    );

    expect(html).toContain('data-event-id="21"');
    expect(html).toContain('data-event-id="25"');
    expect(html).toContain("第一轮工具");
    expect(html).toContain("第二轮工具");
  });
});
