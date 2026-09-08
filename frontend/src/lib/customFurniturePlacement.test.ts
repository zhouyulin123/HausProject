import { describe, expect, it, vi } from "vitest";
import { createCustomFurniturePlacementCoordinator } from "./customFurniturePlacement";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("定制家具场景放置协调器", () => {
  it("并发点击共享同一请求，网络结果未知时复用原幂等键", async () => {
    const first = deferred<{ current_version: number }>();
    const add = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce({ current_version: 2 });
    const coordinator = createCustomFurniturePlacementCoordinator({
      createMutationId: vi.fn().mockReturnValue("stable-placement-id"),
      add,
    });
    const placement = {
      sceneId: 9,
      baseVersion: 1,
      draftClientMutationId: "draft-custom-001",
      position: { x: 0, z: 0 },
      rotationY: 0,
    };

    const pendingA = coordinator.place(placement);
    const pendingB = coordinator.place(placement);
    first.resolve({ current_version: 2 });
    await expect(pendingA).resolves.toEqual({ current_version: 2 });
    await expect(pendingB).resolves.toEqual({ current_version: 2 });
    await expect(coordinator.place(placement)).rejects.toThrow("connection reset");
    await expect(coordinator.place(placement)).resolves.toEqual({ current_version: 2 });

    expect(add).toHaveBeenCalledTimes(3);
    expect(add.mock.calls.every(([request]) =>
      request.clientMutationId === "stable-placement-id"
    )).toBe(true);
  });

  it("权威场景版本变化后生成新的幂等键", async () => {
    const add = vi.fn()
      .mockRejectedValueOnce({ status: 409 })
      .mockResolvedValueOnce({ current_version: 3 });
    const onConflict = vi.fn();
    const coordinator = createCustomFurniturePlacementCoordinator({
      createMutationId: vi.fn()
        .mockReturnValueOnce("stale-placement-id")
        .mockReturnValueOnce("fresh-placement-id"),
      add,
      onConflict,
    });
    const placement = {
      sceneId: 9,
      baseVersion: 1,
      draftClientMutationId: "draft-custom-001",
      position: { x: 0, z: 0 },
      rotationY: 0,
    };

    await expect(coordinator.place(placement)).rejects.toMatchObject({ status: 409 });
    await coordinator.place({ ...placement, baseVersion: 2 });

    expect(onConflict).toHaveBeenCalledTimes(1);
    expect(add.mock.calls[0][0].clientMutationId).toBe("stale-placement-id");
    expect(add.mock.calls[1][0].clientMutationId).toBe("fresh-placement-id");
  });
});
