import { describe, expect, it } from "vitest";
import type { ChatMessage } from "@/types/chat";
import { createPendingSend } from "./ChatPanel";

describe("工作台对话失败重试", () => {
  it("保留同一轮幂等键和单份用户消息", () => {
    const current: ChatMessage[] = [
      { id: "opening", role: "ai", content: "请描述需求" },
    ];
    const pending = createPendingSend(
      "把沙发向左移动",
      current,
      "turn-fixed-id",
      123,
    );

    expect(pending.clientTurnId).toBe("turn-fixed-id");
    expect(pending.messagesWithUser).toEqual([
      ...current,
      { id: "u-123", role: "user", content: "把沙发向左移动" },
    ]);
    expect(
      pending.messagesWithUser.filter((message) => message.role === "user"),
    ).toHaveLength(1);
  });
});
