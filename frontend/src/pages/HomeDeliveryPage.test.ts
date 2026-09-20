import { describe, expect, it } from "vitest";
import { ownerHistoryResult, shareLinkAfterRevoke } from "./HomeDeliveryPage";

describe("冻结交付页面状态隔离", () => {
  it("辅助历史局部失败时保留另一份成功历史", () => {
    const reviews = Promise.resolve({ items: [], next_before_id: null });
    const links = Promise.reject(Error("503"));
    return Promise.allSettled([reviews, links]).then(([reviewResult, linkResult]) => {
      const result = ownerHistoryResult(reviewResult, linkResult);
      expect(result.reviews).not.toBeNull();
      expect(result.links).toBeNull();
      expect(result.error).toBe("分享历史读取失败");
    });
  });

  it("只在撤销当前链接对应的分享时清除一次性链接", () => {
    const current = { shareId: 8, href: "https://example.test/home-share/token" };
    expect(shareLinkAfterRevoke(current, 7)).toBe(current);
    expect(shareLinkAfterRevoke(current, 8)).toBeNull();
  });
});
