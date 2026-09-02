import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import WorkspaceFeedbackControls from "./WorkspaceFeedbackControls";

describe("方案确认反馈控件", () => {
  it("只提供 1-5 满意度选项和显式确认动作，不提供自由文本", () => {
    const html = renderToStaticMarkup(
      <WorkspaceFeedbackControls
        planVersionId={8}
        satisfaction={null}
        delivery={null}
        onSatisfactionChange={vi.fn()}
        onConfirm={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(html).toContain("确认当前方案");
    expect(html).toContain("满意度（可选）");
    for (const score of [1, 2, 3, 4, 5]) {
      expect(html).toContain(`value=\"${score}\"`);
    }
    expect(html).not.toContain("textarea");
  });

  it("没有真实方案版本时禁用确认并说明原因", () => {
    const html = renderToStaticMarkup(
      <WorkspaceFeedbackControls
        planVersionId={null}
        satisfaction={null}
        delivery={null}
        onSatisfactionChange={vi.fn()}
        onConfirm={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(html).toContain("生成服务端方案后可确认");
    expect(html).toContain("disabled=\"\"");
  });

  it("投递失败时显示可理解状态和重试动作", () => {
    const html = renderToStaticMarkup(
      <WorkspaceFeedbackControls
        planVersionId={8}
        satisfaction={4}
        delivery={{
          request: {
            client_event_id: "feedback-42-final-001",
            action_type: "final_select",
            plan_version_id: 8,
            satisfaction_score: 4,
          },
          label: "确认当前方案",
          status: "failed",
          message: "方案确认暂未同步，可重试",
        }}
        onSatisfactionChange={vi.fn()}
        onConfirm={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(html).toContain("方案确认暂未同步，可重试");
    expect(html).toContain("重试同步");
  });
});
