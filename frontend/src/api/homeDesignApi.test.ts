import { describe, it, expect, vi } from "vitest";
vi.mock("./designApi", () => ({ request: vi.fn() }));
import { request } from "./designApi";
import {createHomeQuote,getHomeQuotes,getHomeQuote} from "./homeDesignApi";
it("估价请求严格绑定已保存版本与明确地区",async()=>{
  const payload={home_version:3,region:"CN-SH",client_mutation_id:"same"};await createHomeQuote(12,payload);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/quotes",{method:"POST",body:JSON.stringify(payload)});
  await getHomeQuotes(12,3);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/quotes?home_version=3&limit=10");
  await getHomeQuotes(12,3,8);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/quotes?home_version=3&limit=10&before_id=8");
  await getHomeQuote(12,7);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/quotes/7");
});
import { getHomeDelivery, compareHomeDesigns, getHomeAssetOptions, freezeHomeAsset, getHomeAsset, previewHomeSpaceImpact } from "./homeDesignApi";
import {getHomeDesign,saveHomeDesign,getHomeDesignVersion,getHomeDesignVersions,requestHomeAgent,getHomeAgentHistory} from "./homeDesignApi";
it("家装与建议请求保留任务、版本和分页参数",async()=>{
  await getHomeDesign(12);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design");
  const document={schema_version:"home-design/1.0" as const,space_version:2,objects:[],surfaces:[]};
  const save={document,base_version:3,client_mutation_id:"key"};await saveHomeDesign(12,save);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design",{method:"PUT",body:JSON.stringify(save)});
  await getHomeDesignVersion(12,3);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/versions/3");
  await getHomeDesignVersions(12,3);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/versions?before_version=3");
  await getHomeDesignVersions(12);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/versions");
  const turn={client_turn_id:"turn",base_version:3,space_version:2,message:"添加椅子",region:"CN-SH",budget_max:20000,allowed_asset_ids:[9,12]};await requestHomeAgent(12,turn);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/agent-turns",{method:"POST",body:JSON.stringify(turn)});
  await getHomeAgentHistory(12,7);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/agent-turns?before_id=7");
  await getHomeAgentHistory(12);expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/agent-turns");
});
it("户型影响携带未保存草稿和精确目标版本",async()=>{
  const payload={document:{schema_version:"home-design/1.0" as const,space_version:2,objects:[],surfaces:[]},target_space_version:5};
  await previewHomeSpaceImpact(12,payload);
  expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/space-impact",{method:"POST",body:JSON.stringify(payload)});
});
it("家具来源分页和冻结保持精确来源及幂等键", async () => {
  vi.mocked(request).mockResolvedValue({});
  await getHomeAssetOptions(12, "open_geometry", 9);
  expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/asset-options?kind=open_geometry&limit=20&after_id=9");
  const payload = {client_mutation_id: "retry-key", kind: "product" as const, source_id: 5, source_version: 3};
  await freezeHomeAsset(12, payload);
  expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/assets", {method: "POST", body: JSON.stringify(payload)});
  await getHomeAsset(12, 6);
  expect(request).toHaveBeenLastCalledWith("/api/design/tasks/12/home-design/assets/6");
});
describe("精确版本交付请求", () => {
  it("只请求指定已保存版本", async () => {
    vi.mocked(request).mockResolvedValue({ home_version: 7 });
    await getHomeDelivery(12, 7);
    expect(request).toHaveBeenLastCalledWith(
      "/api/design/tasks/12/home-design/versions/7/delivery",
    );
  });
  it("比较请求显式传递两个版本", async () => {
    await compareHomeDesigns(12, 2, 7);
    expect(request).toHaveBeenLastCalledWith(
      "/api/design/tasks/12/home-design/compare?from_version=2&to_version=7",
    );
  });
  it.each([401, 404, 503])("状态%s不能合成替代清单", async (status) => {
    vi.mocked(request).mockRejectedValueOnce({ status });
    await expect(getHomeDelivery(12, 7)).rejects.toEqual({ status });
  });
});
