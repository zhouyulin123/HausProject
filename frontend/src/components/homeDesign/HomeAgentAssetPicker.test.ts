import { describe, expect, it } from "vitest";
import { updateAllowedAssets } from "./HomeAgentAssetPicker";

describe("AI 家具白名单", () => {
  it("显式加入、移出并保持唯一", () => {
    expect(updateAllowedAssets([3], 3, true)).toEqual([3]);
    expect(updateAllowedAssets([3], 5, true)).toEqual([3, 5]);
    expect(updateAllowedAssets([3, 5], 3, false)).toEqual([5]);
  });

  it("最多允许二十件冻结家具", () => {
    const full = Array.from({ length: 20 }, (_, index) => index + 1);
    expect(() => updateAllowedAssets(full, 21, true)).toThrow("最多允许 AI 使用 20 件家具");
  });
});
