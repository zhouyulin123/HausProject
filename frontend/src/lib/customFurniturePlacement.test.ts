import { describe, expect, it, vi } from "vitest";
import {
  createCustomFurniturePlacementCoordinator,
  placeCustomFurnitureWithConflictRecovery,
  restoreCustomFurnitureDraftReference,
} from "./customFurniturePlacement";

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
  it("从服务端 checkpoint 恢复草稿引用且缺任一事实时失败关闭", () => {
    const spec = { family: "table" as const, name: "餐桌草稿" };
    expect(restoreCustomFurnitureDraftReference(spec, {
      client_mutation_id: "custom-draft-001",
      state_version: 3,
    })).toEqual({
      clientMutationId: "custom-draft-001",
      specSignature: JSON.stringify(spec),
    });
    expect(restoreCustomFurnitureDraftReference(null, {
      client_mutation_id: "custom-draft-001",
      state_version: 3,
    })).toBeNull();
    expect(restoreCustomFurnitureDraftReference(spec, null)).toBeNull();
  });

  it("并发点击共享同一请求，网络结果未知时复用原幂等键", async () => {
    const first = deferred<{ current_version: number }>();
    const add = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValueOnce({ current_version: 2 });
    const coordinator = createCustomFurniturePlacementCoordinator({
      createMutationId: vi.fn()
        .mockReturnValueOnce("first-placement-id")
        .mockReturnValueOnce("retry-placement-id"),
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
    expect(add.mock.calls.map(([request]) => request.clientMutationId)).toEqual([
      "first-placement-id",
      "retry-placement-id",
      "retry-placement-id",
    ]);
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

  it("409 时仅应用重新获取的权威场景，不应用失败请求的本地猜测", async () => {
    const authoritative = { id: 9, current_version: 4 };
    const apply = vi.fn();
    const result = await placeCustomFurnitureWithConflictRecovery({
      place: vi.fn().mockRejectedValue({ status: 409 }),
      reload: vi.fn().mockResolvedValue(authoritative),
      apply,
    });

    expect(result).toBe("conflict_recovered");
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply).toHaveBeenCalledWith(authoritative);
  });

  it("非冲突失败不读取或伪造场景", async () => {
    const reload = vi.fn();
    const apply = vi.fn();
    await expect(placeCustomFurnitureWithConflictRecovery({
      place: vi.fn().mockRejectedValue(new Error("offline")),
      reload,
      apply,
    })).rejects.toThrow("offline");

    expect(reload).not.toHaveBeenCalled();
    expect(apply).not.toHaveBeenCalled();
  });
});
