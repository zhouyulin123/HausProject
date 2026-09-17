import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import RoomSourcePreview from "./RoomSourcePreview";

describe("房间原图预览", () => {
  it("无来源或不安全地址时不渲染图片", () => {
    expect(renderToStaticMarkup(<RoomSourcePreview source={null} />)).toBe("");
    for (const image_url of [null, "javascript:alert(1)", "https://example.test/tracker.png", "/uploads/../api/auth/me"]) {
      const html = renderToStaticMarkup(<RoomSourcePreview source={{ image_id: 1, image_url, file_name: null }} />);
      expect(html).not.toContain("<img");
    }
  });

  it("使用完整原图比例并提供可访问的放大入口", () => {
    const html = renderToStaticMarkup(<RoomSourcePreview source={{ image_id: 8, image_url: "/uploads/8-room.png", file_name: "户型.png" }} />);
    expect(html).toContain('src="/uploads/8-room.png"');
    expect(html).toContain('aria-label="查看原图：户型.png"');
    expect(html).toContain("object-contain");
  });
});
