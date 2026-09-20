import { useCallback, useEffect, useRef, useState } from "react";
import type { HomeAsset, HomeObject } from "@/types/homeDesign";
import type { HomeAssetCache } from "./homeAssets";
export type HomeAssetEntry = {asset?:HomeAsset;error?:string;loading:boolean};
export function useHomeAssets(cache:HomeAssetCache,objects:HomeObject[],enabled=true){
  const ids=enabled?[...new Set(objects.flatMap(o=>o.asset_id?[o.asset_id]:[]))].sort((a,b)=>a-b).join(","):"";
  const [retry,setRetry]=useState(0);
  const [state,setState]=useState<{cache:HomeAssetCache;entries:Record<number,HomeAssetEntry>}>({cache,entries:{}});
  const generation=useRef(0);
  useEffect(()=>{
    const token=++generation.current;
    const wanted=ids?ids.split(",").map(Number):[];
    setState(previous=>({cache,entries:Object.fromEntries(wanted.map(id=>[id,previous.cache===cache && previous.entries[id]?.asset ? previous.entries[id] : {loading:true}]))}));
    wanted.forEach(id=>{void cache.get(id).then(asset=>{
      if(token===generation.current)setState(previous=>({cache,entries:{...previous.entries,[id]:{asset,loading:false}}}));
    }).catch(e=>{
      if(token===generation.current)setState(previous=>({cache,entries:{...previous.entries,[id]:{loading:false,error:e instanceof Error?e.message:"家具读取失败"}}}));
    });});
    return ()=>{++generation.current;};
  },[cache,ids,retry]);
  const renderError=useCallback((id:number)=>{
    cache.invalidateRendered(id);
    setState(previous=>previous.cache===cache?{cache,entries:{...previous.entries,[id]:{loading:false,error:"家具模型无法显示"}}}:previous);
  },[cache]);
  return {entries:state.cache===cache?state.entries:{},retry:()=>setRetry(value=>value+1),renderError};
}
