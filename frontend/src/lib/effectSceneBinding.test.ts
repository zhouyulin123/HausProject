import { describe, expect, it, vi } from "vitest";
import { mockDesigns } from "@/data/mockDesigns";
import { buildSceneDocument } from "./sceneDocument";
import { resolveEffectSceneBinding } from "./effectSceneBinding";

describe("效果图场景绑定恢复", () => {
  it("正式方案首次进入时恢复或创建场景，失败后重试可恢复", async () => {
    const plan = { ...mockDesigns[0], planVersionId: 42 };
    const restored = {
      id: 9,
      plan_version_id: 42,
      current_version: 3,
      scene: buildSceneDocument(plan, "客厅", null),
      validation: { valid: true, errors: [], warnings: [] },
      source: "auto_layout" as const,
    };
    const loadOrCreate = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(restored);

    const failed = await resolveEffectSceneBinding({
      plan,
      primaryRoom: "客厅",
      roomModel: null,
      loadOrCreate,
    });
    const retried = await resolveEffectSceneBinding({
      plan,
      primaryRoom: "客厅",
      roomModel: null,
      loadOrCreate,
    });

    expect(failed).toEqual({
      syncState: "offline",
      sceneId: null,
      sceneVersion: null,
    });
    expect(retried).toEqual({
      syncState: "saved",
      sceneId: 9,
      sceneVersion: 3,
    });
    expect(loadOrCreate).toHaveBeenCalledTimes(2);
    expect(loadOrCreate).toHaveBeenCalledWith(
      42,
      buildSceneDocument(plan, "客厅", null),
    );
  });

  it("仅无服务端 plan version 的本地方案标记为 demo", async () => {
    const loadOrCreate = vi.fn();
    const result = await resolveEffectSceneBinding({
      plan: { ...mockDesigns[0], planVersionId: undefined },
      primaryRoom: "客厅",
      roomModel: null,
      loadOrCreate,
    });

    expect(result.syncState).toBe("demo");
    expect(loadOrCreate).not.toHaveBeenCalled();
  });
});
