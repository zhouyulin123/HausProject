import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { FurnitureItem } from "@/types/furniture";
import FurnitureCard from "./FurnitureCard";


const product: FurnitureItem = {
  id: "1",
  name: "测试沙发",
  category: "沙发",
  room: "客厅",
  style: "现代",
  material: "布艺",
  priceRange: "¥6,800",
  sizeSuggestion: "2200x850x950mm",
  reason: "目录商品",
  alternative: "",
  gradient: "bg-stone-100",
};


describe("FurnitureCard 商品准入", () => {
  it("未通过商业门禁时禁止加入方案", () => {
    const html = renderToStaticMarkup(
      <FurnitureCard
        item={{
          ...product,
          catalogEligibility: {
            eligible: false,
            reasonCodes: ["verification_required"],
          },
        }}
        onOpen={() => undefined}
      />,
    );

    expect(html).toContain("商业信息待核验");
    expect(html).toContain(" disabled=\"\"");
    expect(html).not.toContain("匹配 ");
  });

  it("已准入商品仍可加入方案", () => {
    const html = renderToStaticMarkup(
      <FurnitureCard
        item={{
          ...product,
          catalogEligibility: { eligible: true, reasonCodes: [] },
        }}
        onOpen={() => undefined}
      />,
    );

    expect(html).toContain("加入方案");
    expect(html).not.toContain(" disabled=\"\"");
  });
});
