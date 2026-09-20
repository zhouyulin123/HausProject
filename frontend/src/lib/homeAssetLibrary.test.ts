import { expect, it, vi } from "vitest";
import { HomeAssetLibrary } from "./homeAssetLibrary";
import type { HomeAsset, HomeAssetOption, HomeAssetOptions } from "@/types/homeDesign";
const option = {kind: "product", source_id: 7,source_version: 2,name: "桌子", available: true} as HomeAssetOption;
const asset = {id: 9,task_id: 3,kind: "product",source_id: 7,source_version: 2} as HomeAsset;
it("同一来源版本跨页面实例复用冻结键，来源更新使用新键",async()=>{
  const freeze=vi.fn().mockResolvedValue(asset), api={list:vi.fn(),freeze};
  await new HomeAssetLibrary(3,api).freeze(option);
  await new HomeAssetLibrary(3,api).freeze(option);
  await new HomeAssetLibrary(3,api).freeze({...option,source_version:3});
  expect(freeze.mock.calls[0][1].client_mutation_id).toBe(freeze.mock.calls[1][1].client_mutation_id);
  expect(freeze.mock.calls[2][1].client_mutation_id).not.toBe(freeze.mock.calls[0][1].client_mutation_id);
});
it("冻结失败保留原请求，重试不创建新键", async()=>{
  const freeze=vi.fn().mockRejectedValueOnce(Error("断网")).mockResolvedValue(asset);
  const library=new HomeAssetLibrary(3,{list: vi.fn(),freeze});
  await library.freeze(option);
  expect(library.getSnapshot().error).toContain("断网");
  await library.retry();
  expect(freeze.mock.calls[0]).toEqual(freeze.mock.calls[1]);
  expect(library.getSnapshot().asset).toEqual(asset);
});
it("切换来源忽略迟到列表和冻结结果",async()=>{
  let resolve!: (v: HomeAssetOptions)=>void;
  const library=new HomeAssetLibrary(3,{list: vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValue({items:[],next_after_id:null}),freeze:vi.fn()});
  const old=library.load();
  await library.switchKind("open_geometry");
  resolve({items:[option],next_after_id:null});
  await old;
  expect(library.getSnapshot().options).toEqual([]);
  expect(library.getSnapshot().kind).toBe("open_geometry");
});
it("迟到冻结不覆盖新选择，且不能返回错误来源", async()=>{
  let resolve!: (v: HomeAsset)=>void;
  const freeze=vi.fn().mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValue({...asset,source_version:99});
  const library=new HomeAssetLibrary(3,{list:vi.fn().mockResolvedValue({items:[],next_after_id:null}),freeze});
  const old=library.freeze(option);
  await library.switchKind("open_geometry");
  resolve(asset); await old;
  expect(library.getSnapshot().asset).toBeNull();
  await library.switchKind("product"); await library.freeze(option);
  expect(library.getSnapshot().asset).toBeNull();
  expect(library.getSnapshot().error).toBeTruthy();
});
it("分页合并去重，列表失败可重试且订阅能取消",async()=>{
  const list=vi.fn().mockResolvedValueOnce({items:[option],next_after_id:7}).mockRejectedValueOnce(Error("列表断网")).mockResolvedValueOnce({items:[option,{...option,source_id:8}],next_after_id:null});
  const library=new HomeAssetLibrary(3,{list,freeze:vi.fn()});
  const listener=vi.fn();const unsubscribe=library.subscribe(listener);
  await library.load();await library.load(true);
  expect(library.getSnapshot().error).toBe("列表断网");
  await library.load(true);
  expect(library.getSnapshot().options).toHaveLength(2);
  expect(list).toHaveBeenLastCalledWith(3,"product",7);
  expect(listener).toHaveBeenCalled();unsubscribe();listener.mockClear();
  await library.load(true);await library.retry();await library.freeze({...option,available:false});
  expect(list).toHaveBeenCalledTimes(3);expect(listener).not.toHaveBeenCalled();
});
