import { useEffect, useSyncExternalStore } from "react";
import { Plus, RefreshCw } from "lucide-react";
import type { HomeAsset } from "@/types/homeDesign";
import type { HomeAssetLibrary } from "@/lib/homeAssetLibrary";
export default function HomeAssetLibraryPanel({library,disabled,roomName,onAdd}:{library:HomeAssetLibrary;disabled:boolean;roomName:string;onAdd:(asset:HomeAsset)=>void}){
  const state=useSyncExternalStore(library.subscribe,library.getSnapshot);
  useEffect(()=>{void library.load();},[library]);
  return <section className="hd-library" aria-label="家具库">
    <div className="hd-segment"><button aria-pressed={state.kind==="product"} onClick={()=>void library.switchKind("product")}>商品家具</button><button aria-pressed={state.kind==="open_geometry"} onClick={()=>void library.switchKind("open_geometry")}>本任务作品</button><button aria-label="刷新家具库" title="刷新家具库" disabled={state.loading} onClick={()=>void library.load()}><RefreshCw size={16}/></button></div>
    {state.error && <p role="alert">{state.error}</p>}
    {state.pending && !state.freezing && <button onClick={()=>void library.retry()}>重试冻结</button>}
    {state.freezing && <p role="status">正在冻结家具版本…</p>}
    <div className="hd-asset-options">
      {state.options.map(o=><button key={`${o.kind}-${o.source_id}-${o.source_version}`} disabled={disabled || !o.available || state.freezing} onClick={()=>void library.freeze(o)}>
        <strong>{o.name}</strong><small>{o.source_version ? `来源 V${o.source_version}` : "尚无作品版本"}{o.size ? ` · ${o.size.width} × ${o.size.depth} × ${o.size.height} m` : ""}</small><small>{o.available?"待报价":o.reason || "当前模型不可用"}</small>
      </button>)}
    </div>
    {!state.loading && !state.options.length && <p>暂无可选家具</p>}
    {state.loading && <p role="status">正在读取家具库…</p>}
    {state.next!==null && <button disabled={state.loading} onClick={()=>void library.load(true)}>加载更多家具</button>}
    {state.asset && <div className="hd-frozen-asset"><strong>{state.asset.name}</strong><p>{state.asset.kind==="product"?"商品家具":"本任务作品"} · 冻结来源 V{state.asset.source_version} · 待报价</p><button className="hd-save" disabled={disabled} onClick={()=>onAdd(state.asset!)}><Plus size={16}/>加入{roomName}</button></div>}
  </section>;
}
