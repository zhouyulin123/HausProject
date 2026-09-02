import { describe, expect, it } from "vitest";
import {
  isSceneEditingBlocked,
  sceneSyncPresentation,
} from "./sceneEditingPolicy";

describe("场景首次恢复失败策略", () => {
  it("首次加载失败时禁用编辑并提供重试，恢复成功后开放编辑", () => {
    const failed = {
      syncState: "offline" as const,
      sceneReference: null,
    };

    expect(isSceneEditingBlocked(failed)).toBe(true);
    expect(sceneSyncPresentation(failed)).toMatchObject({
      label: "场景恢复失败 · 点击重试",
      retryable: true,
    });

    const recovered = {
      syncState: "saved" as const,
      sceneReference: { id: 9, version: 1 },
    };
    expect(isSceneEditingBlocked(recovered)).toBe(false);
    expect(sceneSyncPresentation(recovered).retryable).toBe(false);
  });
});
