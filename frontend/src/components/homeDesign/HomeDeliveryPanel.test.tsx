import { renderToStaticMarkup } from "react-dom/server";
import { describe, it, expect } from "vitest";
import { DeliverySummary, homeDeliveryLoadResult } from "./HomeDeliveryPanel";
import type { HomeDelivery, HomeVersionList } from "@/types/homeDesign";
describe("版本交付边界", () => {
  it("版本历史失败时仍交付当前清单，反向失败也保留版本比较", () => {
    const delivery = { home_version: 3 } as HomeDelivery;
    const versions = { versions: [{ version: 3 }] } as HomeVersionList;

    expect(
      homeDeliveryLoadResult(
        { status: "rejected", reason: Error("断网") },
        { status: "fulfilled", value: delivery },
      ),
    ).toEqual({
      versions: null,
      delivery,
      versionError: "版本历史读取失败，请重试。",
      deliveryError: "",
    });
    expect(
      homeDeliveryLoadResult(
        { status: "fulfilled", value: versions },
        { status: "rejected", reason: Error("服务异常") },
      ),
    ).toEqual({
      versions,
      delivery: null,
      versionError: "",
      deliveryError: "当前清单读取失败，请重试。",
    });
  });
  it("显示冻结家具来源版本，不将来源当商业报价", () => {
    const delivery = {home_version:3,space_version:1,validation:{valid:true,issues:[]},gaps:[],limitations:[],lines:[{id:"f",entity_type:"object",room_name:"客厅",name:"沙发",material:{name:"织物"},quantity:1,unit:"piece",quantity_status:"counted",asset:{kind:"product",source_id:5,source_version:8}}]} as unknown as HomeDelivery;
    const html=renderToStaticMarkup(<DeliverySummary delivery={delivery}/>);
    expect(html).toContain("商品家具 #5 · 冻结来源 V8");
    expect(html).toContain("待报价");
  });
  it("展示版本来源、待报价和缺项，缺数量不冒充零", () => {
    const html = renderToStaticMarkup(
      <DeliverySummary
        delivery={{
          schema_version: "home-delivery/1.0",
          task_id: 1,
          home_version: 2,
          space_version: 3,
          purpose: "concept_review",
          lines: [
            {
              entity_type: "surface",
              id: "a",
              room_id: "r",
              room_name: "客厅",
              name: "墙面",
              material: { name: "待选", color: "#ffffff" },
              unit: "m2",
              quantity: null,
              quantity_status: "pending_scale",
              unit_price: null,
              total_price: null,
              price_status: "pending_quote",
            },
          ],
          gaps: [{ code: "pending_scale", entity_type: "surface", id: "a" }],
          limitations: ["不是施工图"],
          validation: { valid: false, issues: [] },
          total_price: null,
          price_status: "pending_quote",
          content_digest: "abc",
          document: null as never,
          space: null as never,
        }}
      />,
    );
    expect(html).toContain("家装 V2");
    expect(html).toContain("空间 V3");
    expect(html).toContain("待报价");
    expect(html).toContain("待确认尺度");
    expect(html).toContain("不是施工图");
  });
});
