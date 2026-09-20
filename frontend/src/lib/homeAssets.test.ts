import { describe, expect, it, vi } from "vitest";
import { HomeAssetCache, homeAssetOffset, objectFromAsset } from "./homeAssets";
import type { HomeAsset } from "@/types/homeDesign";

const asset = { id: 7, task_id: 3, kind: "product", source_id: 2, source_version: 4, name: "沙发", size: { width: 2, height: 1, depth: 0.8 }, material: { name: "织物", color: "#cccccc" }, model_spec: {}, content_digest: "digest" } as HomeAsset;
describe("整屋冻结家具", () => {
  it("已完成缓存保留最近32份，访问会更新顺序",async()=>{
    const fetch=vi.fn(async(_task:number,id:number)=>({...asset,id}));
    const cache=new HomeAssetCache(3,fetch);
    for(let id=1;id<=32;id++)await cache.get(id);
    await cache.get(1);await cache.get(33);await cache.get(1);
    expect(fetch).toHaveBeenCalledTimes(33);
    await cache.get(2);expect(fetch).toHaveBeenCalledTimes(34);
  });
  it("限制并发读取为四个",async()=>{
    const resolves: (()=>void)[]=[];
    const fetch=vi.fn((_task:number,id:number)=>new Promise<HomeAsset>(resolve=>resolves.push(()=>resolve({...asset,id}))));
    const cache=new HomeAssetCache(3,fetch);
    const pending=Array.from({length:6},(_,index)=>cache.get(index+1));
    await Promise.resolve();
    expect(fetch).toHaveBeenCalledTimes(4);
    for(let i=0;i<6;i++){resolves[i]();await new Promise(resolve=>setTimeout(resolve,0));}
    await Promise.all(pending);
  });
  it("加入草稿时复制冻结属性，使用房间中心及底面坐标", () => {
    const object = objectFromAsset(asset, { id: "r", polygon: [{x: 2,z: 4},{x: 6,z: 4},{x: 6,z: 8},{x: 2,z: 8}] });
    expect(object).toMatchObject({ asset_id: 7, name: "沙发", room_id: "r", position: {x: 4,y: 0,z: 6}, size: asset.size, material: asset.material });
    expect(object.size).not.toBe(asset.size);
  });
  it("开放几何用已缩放的中心校正，不能再乘全局缩放", () => {
    const open = {...asset, kind: "open_geometry", model_spec: { 确定性建模规则: {生成器: "open_geometry_v1", 预览规则: {中心_mm: [200,600,-300]}, 全局缩放: [2,2,2]} }} as HomeAsset;
    homeAssetOffset(open).forEach((v,i)=>expect(v).toBeCloseTo([-0.2,-0.1,0.3][i]));
    expect(homeAssetOffset(asset)).toEqual([0,0,0]);
  });
  it("任务内缓存并合并并发读取；失败允许重试", async () => {
    const get = vi.fn().mockRejectedValueOnce(Error("断网")).mockResolvedValue(asset);
    const cache = new HomeAssetCache(3, get);
    await expect(cache.get(7)).rejects.toThrow("断网");
    const values = await Promise.all([cache.get(7), cache.get(7)]);
    expect(values).toEqual([asset, asset]);
    await cache.get(7);
    expect(get).toHaveBeenCalledTimes(2);
    expect(get).toHaveBeenLastCalledWith(3,7);
  });
  it("拒绝串任务和错误资产响应", async () => {
    const cache = new HomeAssetCache(4, vi.fn().mockResolvedValue(asset));
    await expect(cache.get(7)).rejects.toThrow();
  });
  it("缺少开放几何中心不能猜测位置",()=>{
    expect(()=>homeAssetOffset({...asset,kind:"open_geometry"})).toThrow("可信中心");
  });
});
