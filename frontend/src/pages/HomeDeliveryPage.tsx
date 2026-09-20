import {useEffect,useMemo,useRef,useState} from "react";
import {Link,useParams} from "react-router-dom";
import {Printer} from "lucide-react";
import {getDelivery,getDeliveryConfirmations,getDeliveryShares,confirmDelivery,createDeliveryShare,revokeDeliveryShare,type FrozenDelivery,type DeliveryConfirmation,type DeliveryShare} from "@/api/homeDeliveryApi";
import {getHomeAsset} from "@/api/homeDesignApi";
import {HomeAssetCache} from "@/lib/homeAssets";
import {useHomeAssets} from "@/lib/useHomeAssets";
import HomeDeliveryView from "@/components/homeDesign/HomeDeliveryView";
import {parseDesignProjectId} from "@/lib/designWorkspaceRouting";

type Pending={kind:"confirm";payload:Parameters<typeof confirmDelivery>[2]}|{kind:"share";payload:Parameters<typeof createDeliveryShare>[2]};
export type VisibleShareLink={shareId:number;href:string};
export const shareLinkAfterRevoke=(current:VisibleShareLink|null,revokedId:number)=>current?.shareId===revokedId?null:current;
export function ownerHistoryResult(
  reviews: PromiseSettledResult<{items:DeliveryConfirmation[];next_before_id:number|null}>,
  links: PromiseSettledResult<{items:DeliveryShare[];next_before_id:number|null}>,
){
  const failures:string[]=[];
  if(reviews.status==="rejected")failures.push("审阅历史读取失败");
  if(links.status==="rejected")failures.push("分享历史读取失败");
  return {
    reviews:reviews.status==="fulfilled"?reviews.value:null,
    links:links.status==="fulfilled"?links.value:null,
    error:failures.join("；"),
  };
}
function OwnerDelivery({taskId,id}:{taskId:number;id:number}){
  const [delivery,setDelivery]=useState<FrozenDelivery|null>(null),[confirmations,setConfirmations]=useState<DeliveryConfirmation[]>([]),[shares,setShares]=useState<DeliveryShare[]>([]),[error,setError]=useState(""),[historyError,setHistoryError]=useState(""),[busy,setBusy]=useState(false),[historyBusy,setHistoryBusy]=useState(false),[decision,setDecision]=useState<"reviewed"|"needs_changes">("reviewed"),[note,setNote]=useState(""),[consent,setConsent]=useState(false),[hours,setHours]=useState(24),[link,setLink]=useState<VisibleShareLink|null>(null);
  const key=`haus-delivery-action-${taskId}-${id}`;const pending=useRef<Pending|null>(null),generation=useRef(0),historyGeneration=useRef(0);
  const [reviewNext,setReviewNext]=useState<number|null>(null),[shareNext,setShareNext]=useState<number|null>(null);
  const [loadAssets,setLoadAssets]=useState(false);
  const cache=useMemo(()=>new HomeAssetCache(taskId,getHomeAsset),[taskId]);const assets=useHomeAssets(cache,delivery?.snapshot.document.objects??[],loadAssets);
  const reload=async()=>{
    const token=++generation.current,historyToken=++historyGeneration.current;setBusy(true);setError("");setHistoryError("");
    try{const result=await getDelivery(taskId,id);
      if(token!==generation.current)return;if(result.task_id!==taskId||result.id!==id)throw Error("交付归属不匹配");setDelivery(result);setBusy(false);setHistoryBusy(true);
      const [reviews,links]=await Promise.allSettled([getDeliveryConfirmations(taskId,id),getDeliveryShares(taskId)]);
      if(historyToken!==historyGeneration.current)return;
      const history=ownerHistoryResult(reviews,links);
      if(history.reviews){setConfirmations(history.reviews.items);setReviewNext(history.reviews.next_before_id);}
      if(history.links){setShares(history.links.items);setShareNext(history.links.next_before_id);}
      setHistoryError(history.error);
    }catch(e){if(token===generation.current)setError(e instanceof Error?e.message:"交付读取失败");}finally{if(token===generation.current)setBusy(false);if(historyToken===historyGeneration.current)setHistoryBusy(false);}
  };
  const more=async(kind:"review"|"share")=>{
    const cursor=kind==="review"?reviewNext:shareNext;if(busy||!cursor)return;
    const token=++generation.current;setBusy(true);setError("");
    try{if(kind==="review"){const result=await getDeliveryConfirmations(taskId,id,cursor);if(token!==generation.current)return;setConfirmations(old=>[...old,...result.items.filter(item=>!old.some(p=>p.id===item.id))]);setReviewNext(result.next_before_id);}
      else{const result=await getDeliveryShares(taskId,cursor);if(token!==generation.current)return;setShares(old=>[...old,...result.items.filter(item=>!old.some(p=>p.id===item.id))]);setShareNext(result.next_before_id);}
    }catch(e){if(token===generation.current)setError(e instanceof Error?e.message:"历史读取失败");}finally{if(token===generation.current)setBusy(false);}
  };
  useEffect(()=>{try{const value=JSON.parse(localStorage.getItem(key)??"null");if(["confirm","share"].includes(value?.kind)&&typeof value?.payload?.client_mutation_id==="string")pending.current=value;}catch{setError("本机重试记录无法恢复");}void reload();return()=>{generation.current++;historyGeneration.current++;};},[taskId,id]);
  const mutate=async(action:Pending)=>{
    if(busy)return;const token=++generation.current;setBusy(true);setError("");
    try{pending.current??=action;localStorage.setItem(key,JSON.stringify(pending.current));const current=pending.current;
      if(current.kind==="confirm"){const review=await confirmDelivery(taskId,id,current.payload);if(token!==generation.current)return;setConfirmations(old=>[review,...old.filter(item=>item.id!==review.id)]);}
      else{const share=await createDeliveryShare(taskId,id,current.payload);if(token!==generation.current)return;setShares(old=>[share,...old.filter(item=>item.id!==share.id)]);if(share.share_url)setLink({shareId:share.id,href:new URL(share.share_url,window.location.origin).href});if(share.replayed)setError("此分享已创建，但链接仅首次返回。可按记录撤销后重新创建。");}
      localStorage.removeItem(key);pending.current=null;
    }catch(e){if(token===generation.current){if((e as {status?:number})?.status===422){pending.current=null;localStorage.removeItem(key);}setError(e instanceof Error?e.message:"请求失败，请重试原操作");}}finally{if(token===generation.current)setBusy(false);}
  };
  const revoke=async(share:number)=>{if(busy)return;setBusy(true);setError("");try{await revokeDeliveryShare(taskId,share);setLink(current=>shareLinkAfterRevoke(current,share));setShares(old=>old.map(item=>item.id===share?{...item,revoked_at:new Date().toISOString()}:item));}catch(e){setError(e instanceof Error?e.message:"撤销失败，请重试");}finally{setBusy(false);}};
  return <main className="hdelivery"><nav className="hdelivery-nav"><Link to={`/design/${taskId}/home-design`}>返回设计</Link><button onClick={()=>window.print()} title="打印交付"><Printer size={18}/></button></nav>
    {error&&<p role="alert">{error}</p>}{historyError&&<p role="alert">{historyError}；交付正文仍可查看，可重新读取。</p>}{!delivery&&<button disabled={busy} onClick={()=>void reload()}>{busy?"正在读取交付…":"重新读取交付"}</button>}
    {delivery&&<><HomeDeliveryView snapshot={delivery.snapshot} assets={assets.entries} onAssetError={assets.renderError} onNeedsAssets={()=>setLoadAssets(true)}/>
      <section className="hdelivery-actions"><h2>审阅与分享</h2><p>交付 #{id} · {new Date(delivery.created_at).toLocaleString()}</p>{historyBusy&&<p role="status">正在读取审阅与分享历史…</p>}{historyError&&<button disabled={busy||historyBusy} onClick={()=>void reload()}>重新读取辅助历史</button>}
        {Object.values(assets.entries).some(value=>value.error)&&<button onClick={assets.retry}>重试家具模型</button>}
        {pending.current&&<><button disabled={busy} onClick={()=>void mutate(pending.current!)}>重试原操作</button><button disabled={busy} onClick={()=>{if(window.confirm("仅解除本机重试记录，不会撤销已创建的审阅或分享。请先核对服务端记录，确认继续？")){try{localStorage.removeItem(key);pending.current=null;setError("已解除本机重试记录，请核对审阅与分享历史。");}catch{setError("无法解除本机重试记录");}}}}>解除本机重试记录</button></>}
        <fieldset disabled={busy||!!pending.current}><label>审阅结果<select value={decision} onChange={e=>setDecision(e.target.value as typeof decision)}><option value="reviewed">已审阅</option><option value="needs_changes">需要修改</option></select></label><label>审阅备注<textarea value={note} onChange={e=>setNote(e.target.value)} maxLength={1000}/></label><button onClick={()=>void mutate({kind:"confirm",payload:{client_mutation_id:crypto.randomUUID(),snapshot_digest:delivery.content_digest,decision,note}})}>记录审阅结果</button></fieldset>
        {confirmations.map(item=><p key={item.id}>{item.decision==="reviewed"?"已审阅":"需要修改"} · {new Date(item.created_at).toLocaleString()} · {item.note}</p>)}
        {reviewNext&&<button disabled={busy} onClick={()=>void more("review")}>更多审阅记录</button>}
        <fieldset disabled={busy||!!pending.current}><label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>我同意链接接收者查看户型、尺寸、点位、填写的名称、材料清单及已附估价（包括分项价格）；不包含原图及私有模型。撤销不能收回已下载内容。</label><label>有效期（小时）<input type="number" min={1} max={720} value={hours} onChange={e=>setHours(Number(e.target.value))}/></label><button disabled={!consent||!Number.isInteger(hours)||hours<1||hours>720} onClick={()=>void mutate({kind:"share",payload:{client_mutation_id:crypto.randomUUID(),consent_public:true,expires_in_hours:hours,include_private_models:false,include_source_image:false}})}>创建分享链接</button></fieldset>
        {link&&<p>分享 #{link.shareId}：<a href={link.href} target="_blank" rel="noreferrer">{link.href}</a></p>}
        {shares.map(share=><article key={share.id}>分享 #{share.id} · 交付 #{share.delivery_id} · {share.revoked_at?"已撤销":`到期 ${new Date(share.expires_at).toLocaleString()}`} {!share.revoked_at&&<button disabled={busy} onClick={()=>void revoke(share.id)}>撤销分享 #{share.id}</button>}</article>)}
        {shareNext&&<button disabled={busy} onClick={()=>void more("share")}>更多分享记录</button>}
      </section></>}
  </main>;
}
export default function HomeDeliveryPage(){const {projectId,deliveryId}=useParams();const taskId=parseDesignProjectId(projectId),id=parseDesignProjectId(deliveryId);return taskId&&id?<OwnerDelivery key={`${taskId}-${id}`} taskId={taskId} id={id}/>:<main className="hdelivery">交付地址无效</main>;}
