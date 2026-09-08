import { describe, expect, it, vi } from "vitest";
import { createTaskTimelinePollingLoop } from "./taskTimelinePolling";

function deferred() {
  let resolve!: () => void;
  let reject!: () => void;
  const promise = new Promise<void>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("任务时间线增量轮询", () => {
  it("同一时刻只允许一个请求，hidden 暂停且恢复立即拉取", async () => {
    let hidden = false;
    const first = deferred();
    const poll = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(undefined);
    const schedule = vi.fn(() => 1);
    const clear = vi.fn();
    const loop = createTaskTimelinePollingLoop({
      poll,
      isHidden: () => hidden,
      schedule,
      clear,
      baseDelayMs: 5_000,
      maxDelayMs: 40_000,
    });

    loop.start();
    loop.visibilityChanged();
    expect(poll).toHaveBeenCalledTimes(1);

    hidden = true;
    loop.visibilityChanged();
    first.resolve();
    await first.promise;
    await Promise.resolve();
    expect(schedule).not.toHaveBeenCalled();

    hidden = false;
    loop.visibilityChanged();
    await Promise.resolve();
    expect(poll).toHaveBeenCalledTimes(2);
    loop.stop();
  });

  it("失败时退避，成功后恢复基础间隔并保留循环", async () => {
    const timers: Array<() => void> = [];
    const poll = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined);
    const schedule = vi.fn((callback: () => void) => {
      timers.push(callback);
      return timers.length;
    });
    const loop = createTaskTimelinePollingLoop({
      poll,
      isHidden: () => false,
      schedule,
      clear: vi.fn(),
      baseDelayMs: 5_000,
      maxDelayMs: 40_000,
    });

    loop.start();
    await Promise.resolve();
    await Promise.resolve();
    expect(schedule).toHaveBeenLastCalledWith(expect.any(Function), 10_000);

    timers.pop()?.();
    await Promise.resolve();
    await Promise.resolve();
    expect(schedule).toHaveBeenLastCalledWith(expect.any(Function), 5_000);
    loop.stop();
  });
});
