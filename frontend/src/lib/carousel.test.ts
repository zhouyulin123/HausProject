import { describe, expect, it } from "vitest";
import { mockStyles } from "@/data/mockStyles";
import { getNextSlideIndex, getPreviousSlideIndex } from "./carousel";

describe("carousel", () => {
  it("下一张在末尾时回到第一张", () => {
    expect(getNextSlideIndex(2, 3)).toBe(0);
  });

  it("上一张在开头时回到最后一张", () => {
    expect(getPreviousSlideIndex(0, 3)).toBe(2);
  });

  it("无可用图片时始终返回安全索引", () => {
    expect(getNextSlideIndex(4, 0)).toBe(0);
    expect(getPreviousSlideIndex(4, 0)).toBe(0);
  });

  it("八种风格各配置三张不重复的案例图片", () => {
    const imageGroups = mockStyles.map((style) =>
      "images" in style ? style.images : [],
    );
    const allImages = imageGroups.flat();

    expect(imageGroups).toHaveLength(8);
    expect(imageGroups.every((images) => images.length === 3)).toBe(true);
    expect(new Set(allImages).size).toBe(24);
  });
});
