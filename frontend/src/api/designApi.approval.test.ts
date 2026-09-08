import { afterEach, describe, expect, it, vi } from "vitest";

function storage(sessionId: string): Storage {
  const values = new Map([["haus-anonymous-session-id", sessionId]]);
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Agent 审批 API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("读取任务审批并以服务端幂等键提交用户决定", async () => {
    const sessionId = "f5f4de50-783f-4d0d-86d9-d5963775505c";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      if (path === `/api/sessions/${sessionId}`) return json({ session_id: sessionId });
      if (path.endsWith("/agent-approvals") && !init?.method) {
        return json({ approvals: [{ id: 9, status: "pending" }] });
      }
      if (path.endsWith("/agent-approvals/9/decision")) {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({
          client_decision_id: "approval-42-9-001",
          decision: "reject",
          conclusion: "房间尺寸需要重测",
        });
        return json({ id: 9, status: "rejected" });
      }
      throw new Error(`未处理的请求: ${path}`);
    });
    vi.stubGlobal("window", { localStorage: storage(sessionId) });
    vi.stubGlobal("fetch", fetchMock);

    const { decideAgentApproval, fetchAgentApprovals } = await import("./designApi");
    expect((await fetchAgentApprovals(42))[0]?.id).toBe(9);
    expect((await decideAgentApproval(42, 9, {
      clientDecisionId: "approval-42-9-001",
      decision: "reject",
      conclusion: "房间尺寸需要重测",
    })).status).toBe("rejected");
  });
});
