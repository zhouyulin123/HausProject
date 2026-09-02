import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CustomFurnitureDraftConflictError,
  createCustomFurnitureDraftSaveCoordinator,
} from "./customFurnitureDraftQueue";
import { createCustomFurnitureDraft } from "./customFurnitureWorkspace";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("定制家具草稿串行协调器", () => {
  afterEach(() => vi.useRealTimers());

  it("延迟的旧响应不会覆盖更新后的草稿", async () => {
    vi.useFakeTimers();
    const first = deferred<{ state_version: number }>();
    const second = deferred<{ state_version: number }>();
    const save = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const onSynced = vi.fn();
    const coordinator = createCustomFurnitureDraftSaveCoordinator({
      initialStateVersion: 0,
      debounceMs: 600,
      createMutationId: vi.fn()
        .mockReturnValueOnce("draft-a")
        .mockReturnValueOnce("draft-b"),
      save,
      onSynced,
      onError: vi.fn(),
    });
    const draftA = createCustomFurnitureDraft("table");
    const draftB = { ...draftA, name: "更新后的餐桌" };

    coordinator.schedule(draftA);
    await vi.advanceTimersByTimeAsync(600);
    coordinator.schedule(draftB);
    await vi.advanceTimersByTimeAsync(600);
    first.resolve({ state_version: 1 });
    await flushPromises();

    expect(save).toHaveBeenNthCalledWith(2, expect.objectContaining({
      baseStateVersion: 1,
      spec: draftB,
    }));
    expect(onSynced).not.toHaveBeenCalled();

    second.resolve({ state_version: 2 });
    await flushPromises();
    expect(onSynced).toHaveBeenCalledTimes(1);
    expect(onSynced).toHaveBeenCalledWith(expect.objectContaining({
      stateVersion: 2,
      spec: draftB,
    }));
  });

  it("状态持续冲突时只做有界重试", async () => {
    vi.useFakeTimers();
    const draft = createCustomFurnitureDraft("cabinet");
    const save = vi.fn().mockImplementation(({ baseStateVersion }) =>
      Promise.reject(new CustomFurnitureDraftConflictError({
        stateVersion: baseStateVersion + 1,
        customFurnitureDraft: null,
        sceneRef: null,
      })),
    );
    const onError = vi.fn();
    const coordinator = createCustomFurnitureDraftSaveCoordinator({
      initialStateVersion: 0,
      debounceMs: 600,
      maxConflictRetries: 2,
      createMutationId: vi.fn()
        .mockReturnValueOnce("draft-1")
        .mockReturnValueOnce("draft-2")
        .mockReturnValueOnce("draft-3"),
      save,
      onSynced: vi.fn(),
      onError,
    });

    coordinator.schedule(draft);
    await vi.advanceTimersByTimeAsync(600);
    await flushPromises();

    expect(save).toHaveBeenCalledTimes(3);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ retryable: true }));
  });
});
