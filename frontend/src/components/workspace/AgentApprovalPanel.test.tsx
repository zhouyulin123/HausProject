import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import AgentApprovalPanel from "./AgentApprovalPanel";
import type { AgentApproval } from "@/api/designApi";

function approval(overrides: Partial<AgentApproval>): AgentApproval {
  return {
    id: 1,
    task_id: 42,
    turn_id: 7,
    approval_type: "quote_review",
    status: "pending",
    request_reason: "报价规则缺失，需要人工确认",
    reason_code: "quote_rule_missing",
    request_context: {},
    requested_at: "2026-09-08T08:00:00Z",
    client_decision_id: null,
    decision: null,
    conclusion: null,
    decided_by_type: null,
    decided_by_id: null,
    decided_at: null,
    resolution_code: null,
    agent_status: null,
    task_status: null,
    exit_reason: null,
    next_action: null,
    ...overrides,
  };
}

describe("Agent 人工审批区", () => {
  it("展示待处理原因并为普通审批提供确认与驳回入口", () => {
    const html = renderToStaticMarkup(
      <AgentApprovalPanel
        approvals={[approval({})]}
        loading={false}
        error=""
        decidingId={null}
        onDecision={vi.fn()}
      />,
    );

    expect(html).toContain("报价复核");
    expect(html).toContain("报价规则缺失，需要人工确认");
    expect(html).toContain("确认");
    expect(html).toContain("驳回");
  });

  it("施工风险不向用户提供批准入口并显示受控复核边界", () => {
    const html = renderToStaticMarkup(
      <AgentApprovalPanel
        approvals={[approval({ approval_type: "construction_risk" })]}
        loading={false}
        error=""
        decidingId={null}
        onDecision={vi.fn()}
      />,
    );

    expect(html).toContain("施工风险");
    expect(html).toContain("只能由管理员受控复核");
    expect(html).not.toContain(">确认<");
    expect(html).toContain("驳回");
  });

  it("展示已完成结论而不再渲染决定按钮", () => {
    const html = renderToStaticMarkup(
      <AgentApprovalPanel
        approvals={[approval({ status: "rejected", conclusion: "尺寸需要重新测量" })]}
        loading={false}
        error=""
        decidingId={null}
        onDecision={vi.fn()}
      />,
    );

    expect(html).toContain("已驳回");
    expect(html).toContain("尺寸需要重新测量");
    expect(html).not.toContain("填写审核结论");
  });
});
