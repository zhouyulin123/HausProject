import {beforeEach,expect,it,vi} from "vitest";
import type {HomeAsset,HomeObject} from "@/types/homeDesign";
const hooks=vi.hoisted(()=>({states:[] as unknown[],cursor:0,effect:null as null|(()=>void|(()=>void)),ref:{current:0}}));
vi.mock("react",()=>({
  useState:(initial:unknown)=>{const i=hooks.cursor++;if(!(i in hooks.states))hooks.states[i]=initial;return [hooks.states[i],(next:unknown)=>{hooks.states[i]=typeof next==="function"?(next as (v:unknown)=>unknown)(hooks.states[i]):next;}];},
  useEffect:(f:()=>void|(()=>void))=>{hooks.effect=f;},useRef:()=>hooks.ref,useCallback:(f:unknown)=>f,
}));
import {useHomeAssets} from "./useHomeAssets";
import {HomeAssetCache} from "./homeAssets";
const asset={id:7,task_id:3} as HomeAsset;
const objects=[{asset_id:7}] as HomeObject[];
function render(cache:HomeAssetCache,items=objects,enabled=true){hooks.cursor=0;return useHomeAssets(cache,items,enabled);}
async function settle(){await new Promise(resolve=>setTimeout(resolve,0));}
beforeEach(()=>{hooks.states=[];hooks.cursor=0;hooks.ref.current=0;hooks.effect=null;});
it("跨任务切换立即隐藏旧资产，迟到结果不能回来",async()=>{
  let resolve!:(v:HomeAsset)=>void;
  const first=new HomeAssetCache(3,()=>new Promise(r=>{resolve=r}));
  render(first);const cleanup=hooks.effect!();
  if(cleanup)cleanup();
  const second=new HomeAssetCache(4,vi.fn().mockResolvedValue({...asset,task_id:4}));
  expect(render(second).entries).toEqual({});hooks.effect!();
  await settle();
  resolve(asset);await settle();
  expect(render(second).entries[7].asset?.task_id).toBe(4);
});
it("错误可重试，渲染错误不继续标为成功模型",async()=>{
  const fetch=vi.fn().mockRejectedValueOnce(Error("断网")).mockResolvedValue(asset);
  const cache=new HomeAssetCache(3,fetch);
  render(cache);hooks.effect!();await settle();
  expect(render(cache).entries[7].error).toBe("断网");
  render(cache).retry();render(cache);hooks.effect!();await settle();
  expect(render(cache).entries[7].asset).toEqual(asset);
  render(cache).renderError(7);
  expect(render(cache).entries[7]).toEqual({loading:false,error:"家具模型无法显示"});
  render(cache).retry();render(cache);hooks.effect!();await settle();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(render(cache).entries[7].asset).toEqual(asset);
});
it("二维视图不读取家具模型，启用三维后才加载",async()=>{
  const fetch=vi.fn().mockResolvedValue(asset);
  const cache=new HomeAssetCache(3,fetch);
  render(cache,objects,false);hooks.effect!();await settle();
  expect(fetch).not.toHaveBeenCalled();
  expect(render(cache,objects,false).entries).toEqual({});
  render(cache,objects,true);hooks.effect!();await settle();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(render(cache,objects,true).entries[7].asset).toEqual(asset);
});
