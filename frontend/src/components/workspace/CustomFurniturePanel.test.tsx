import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import CustomFurniturePanel from "./CustomFurniturePanel";

describe("自定义家具结构化面板", () => {
  it("显示家具族、毫米尺寸和服务端待确认提示", () => {
    const html = renderToStaticMarkup(
      <CustomFurniturePanel
        taskId={42}
        initialSpec={null}
        preview={null}
        approvalRequired={false}
        pendingQuestions={[
          {
            field: "custom_furniture_spec.dimensions",
            prompt: "请提供宽、高、深三个毫米尺寸。",
            reason: "完整毫米尺寸是几何生成和报价复算的必要输入",
          },
        ]}
        onAgentResponse={vi.fn()}
        onConversationTurn={vi.fn()}
      />,
    );

    expect(html).toContain("柜体");
    expect(html).toContain("桌类");
    expect(html).toContain("宽度（mm）");
    expect(html).toContain("请提供宽、高、深三个毫米尺寸。");
    expect(html).toContain("生成参数预览");
  });
});
