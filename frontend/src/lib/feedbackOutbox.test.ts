import { describe, expect, it, vi } from "vitest";
import type { DesignFeedbackEventRequest } from "@/types/feedback";
import {
  FEEDBACK_OUTBOX_MAX_BYTES,
  FEEDBACK_OUTBOX_MAX_EVENTS,
  createFeedbackOutbox,
  feedbackOutboxStorageKey,
  readFeedbackOutbox,
} from "./feedbackOutbox";

function createStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
}

function createOnlineTarget() {
  const listeners = new Set<EventListener>();
  return {
    addEventListener: vi.fn((_type: string, listener: EventListener) => listeners.add(listener)),
    removeEventListener: vi.fn((_type: string, listener: EventListener) => listeners.delete(listener)),
    dispatchOnline: () => listeners.forEach((listener) => listener(new Event("online"))),
  };
}

function finalSelect(id: string, planVersionId = 8): DesignFeedbackEventRequest {
  return {
    client_event_id: id,
    action_type: "final_select",
    plan_version_id: planVersionId,
    satisfaction_score: 4,
  };
}

async function settlePromises() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("反馈 outbox", () => {
  it("发送失败后跨页面刷新恢复，并在服务端确认后删除", async () => {
    const storage = createStorage();
    const firstSend = vi.fn().mockRejectedValue(new Error("offline"));
    const first = createFeedbackOutbox({ taskId: 42, storage, send: firstSend });

    first.start();
    first.submit(finalSelect("feedback-42-final-refresh"), "用户输入不应写入持久层");
    await settlePromises();

    expect(firstSend).toHaveBeenCalledTimes(1);
    expect(readFeedbackOutbox(storage, 42)).toEqual([{
      request: finalSelect("feedback-42-final-refresh"),
      label: "确认当前方案",
    }]);
    expect(storage.getItem(feedbackOutboxStorageKey(42)!)).not.toContain("用户输入");
    first.stop();

    const recoveredSend = vi.fn().mockResolvedValue({});
    const recovered = createFeedbackOutbox({ taskId: 42, storage, send: recoveredSend });
    recovered.start();
    await settlePromises();

    expect(recoveredSend).toHaveBeenCalledWith(42, finalSelect("feedback-42-final-refresh"));
    expect(readFeedbackOutbox(storage, 42)).toEqual([]);
  });

  it("服务端失败时保留事件，成功时只删除已确认事件", async () => {
    const storage = createStorage();
    const send = vi.fn()
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce({});
    const outbox = createFeedbackOutbox({ taskId: 42, storage, send });
    const first = finalSelect("feedback-42-final-failed");
    const second = finalSelect("feedback-42-final-sent", 9);

    outbox.start();
    outbox.submit(first, "确认当前方案");
    await settlePromises();
    expect(readFeedbackOutbox(storage, 42).map((item) => item.request)).toEqual([first]);

    outbox.submit(second, "确认当前方案");
    await settlePromises();
    expect(readFeedbackOutbox(storage, 42).map((item) => item.request)).toEqual([first]);
  });

  it("按 taskId 隔离，且非正整数任务不会读取、写入或发送", async () => {
    const storage = createStorage();
    const task42 = createFeedbackOutbox({
      taskId: 42,
      storage,
      send: vi.fn().mockRejectedValue(new Error("offline")),
    });
    task42.submit(finalSelect("feedback-42-final-isolated"), "确认当前方案");
    await settlePromises();

    const otherSend = vi.fn().mockResolvedValue({});
    const task43 = createFeedbackOutbox({ taskId: 43, storage, send: otherSend });
    task43.start();
    await settlePromises();
    expect(otherSend).not.toHaveBeenCalled();
    expect(readFeedbackOutbox(storage, 42)).toHaveLength(1);

    const getItem = vi.spyOn(storage, "getItem");
    const setItem = vi.spyOn(storage, "setItem");
    const invalidSend = vi.fn();
    const invalid = createFeedbackOutbox({ taskId: 0, storage, send: invalidSend });
    invalid.start();
    invalid.submit(finalSelect("feedback-invalid"), "确认当前方案");
    await settlePromises();
    expect(getItem).not.toHaveBeenCalledWith(expect.stringContaining(":0"));
    expect(setItem).not.toHaveBeenCalledWith(expect.stringContaining(":0"), expect.anything());
    expect(invalidSend).not.toHaveBeenCalled();
  });

  it("畸形、跨任务、超大及超量数据 fail closed 并清理当前任务分区", () => {
    const key = feedbackOutboxStorageKey(42)!;
    const malformedPayloads = [
      "not-json",
      JSON.stringify({ version: 1, task_id: 43, entries: [] }),
      JSON.stringify({
        version: 1,
        task_id: 42,
        entries: [{
          request: { ...finalSelect("feedback-42-extra"), url: "https://private.invalid" },
          label: "确认当前方案",
        }],
      }),
      "x".repeat(FEEDBACK_OUTBOX_MAX_BYTES + 1),
      JSON.stringify({
        version: 1,
        task_id: 42,
        entries: Array.from({ length: FEEDBACK_OUTBOX_MAX_EVENTS + 1 }, (_, index) => ({
          request: finalSelect(`feedback-42-overflow-${index}`),
          label: "确认当前方案",
        })),
      }),
    ];

    for (const payload of malformedPayloads) {
      const storage = createStorage({ [key]: payload });
      expect(readFeedbackOutbox(storage, 42)).toEqual([]);
      expect(storage.getItem(key)).toBeNull();
    }
  });

  it("online 自动重试，挂载恢复与重复 online 不会并发同一事件", async () => {
    const key = feedbackOutboxStorageKey(42)!;
    const request = finalSelect("feedback-42-final-online");
    const storage = createStorage({
      [key]: JSON.stringify({
        version: 1,
        task_id: 42,
        entries: [{ request, label: "确认当前方案" }],
      }),
    });
    const onlineTarget = createOnlineTarget();
    let resolveSend!: () => void;
    const send = vi.fn(() => new Promise<void>((resolve) => { resolveSend = resolve; }));
    const outbox = createFeedbackOutbox({ taskId: 42, storage, send, onlineTarget });

    outbox.start();
    onlineTarget.dispatchOnline();
    onlineTarget.dispatchOnline();
    await settlePromises();
    expect(send).toHaveBeenCalledTimes(1);

    resolveSend();
    await settlePromises();
    expect(readFeedbackOutbox(storage, 42)).toEqual([]);
    expect(onlineTarget.addEventListener).toHaveBeenCalledWith("online", expect.any(Function));

    outbox.stop();
    expect(onlineTarget.removeEventListener).toHaveBeenCalledWith("online", expect.any(Function));
  });
});
