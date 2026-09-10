import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "@/types/chat";
import { ApiError } from "@/api/designApi";
import {
  AgentStateConflictRefreshError,
  buildWorkspaceAgentTurn,
  createPendingSend,
  recoverWorkspaceAgentConflict,
  workspaceAgentSendFailure,
} from "./ChatPanel";

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

  it("每轮都携带当前 Agent 状态版本", () => {
    const pending = createPendingSend("把沙发向左移动", [], "turn-1", 123);

    expect(buildWorkspaceAgentTurn(pending, {
      activeMode: "catalog_design",
      activeRoomId: "living-room",
      sceneId: 7,
      baseSceneVersion: 3,
      baseStateVersion: 12,
    })).toMatchObject({
      client_turn_id: "turn-1",
      message: "把沙发向左移动",
      base_state_version: 12,
    });
  });

  it("状态冲突显示明确文案且不提供语义重试", () => {
    expect(workspaceAgentSendFailure(new ApiError("conflict", 409, {
      code: "agent_state_conflict",
      message: "状态版本冲突",
    }))).toEqual({
      message: "设计状态已被更新，请查看最新结果后重新发送需求。",
      retryable: false,
    });
  });

  it("状态冲突先恢复权威 checkpoint 且不自动重放原请求", async () => {
    const refresh = vi.fn(async () => undefined);
    const error = new ApiError("conflict", 409, {
      code: "agent_state_conflict",
      message: "状态版本冲突",
    });

    await expect(recoverWorkspaceAgentConflict(error, refresh)).resolves.toBe(true);
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("状态冲突且 checkpoint 恢复失败时要求刷新，不允许语义重试", async () => {
    const error = new ApiError("conflict", 409, {
      code: "agent_state_conflict",
    });

    await expect(recoverWorkspaceAgentConflict(
      error,
      async () => { throw new Error("network"); },
    )).rejects.toBeInstanceOf(AgentStateConflictRefreshError);
    expect(workspaceAgentSendFailure(new AgentStateConflictRefreshError())).toEqual({
      message: "设计状态已变化，但最新状态读取失败。请刷新页面后再继续。",
      retryable: false,
    });
  });

  it("其他服务端错误直接展示服务端消息", () => {
    expect(workspaceAgentSendFailure(new ApiError("failed", 422, {
      code: "invalid_turn",
      message: "请先补充房间尺寸",
    }))).toEqual({
      message: "请先补充房间尺寸",
      retryable: true,
    });
  });
});
