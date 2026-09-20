import {useState} from "react";
import type {DeliverySnapshot} from "@/api/homeDeliveryApi";
import HomeDesignCanvas from "./HomeDesignCanvas";
import type {HomeAssetEntry} from "@/lib/useHomeAssets";
import {pointLabels} from "./homeDesignFields";
import HomeQuoteEvidence from "./HomeQuoteEvidence";
import "./homeDelivery.css";

export default function HomeDeliveryView({snapshot,assets={},onAssetError,onNeedsAssets}:{snapshot:DeliverySnapshot;assets?:Record<number,HomeAssetEntry>;onAssetError?:(id:number)=>void;onNeedsAssets?:()=>void}){
  const [room,setRoom]=useState("");const [mode,setMode]=useState<"2d"|"3d">("2d");
  const money=(value:number|null)=>value===null?"待报价":`${value.toLocaleString("zh-CN")} 元`;
  return <>
    <h1>整屋设计方案</h1><p>家装 V{snapshot.home_version} · 户型 V{snapshot.space_version}</p>
    <div className="hdelivery-controls">
      <label>查看房间<select value={room} onChange={e=>setRoom(e.target.value)}><option value="">整屋</option>{snapshot.space.rooms.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      <div role="group" aria-label="视图"><button aria-pressed={mode==="2d"} onClick={()=>setMode("2d")}>2D</button><button aria-pressed={mode==="3d"} onClick={()=>{onNeedsAssets?.();setMode("3d");}}>3D</button></div>
    </div>
    <div className="hdelivery-scene"><HomeDesignCanvas space={snapshot.space} document={snapshot.document} roomId={room} mode={mode} selected={null} onSelect={()=>{}} showCeiling={false} assets={assets} onAssetError={onAssetError}/></div>
    <section><h2>检查与估价</h2><p>{snapshot.validation.valid?"当前概念几何检查通过，不代表可施工。":"存在待修正或待确认的问题。"}</p>
      {snapshot.validation.issues.map((issue,i)=><p key={i}>{issue.message}</p>)}
      {snapshot.quote?<><p>已知小计：{money(snapshot.quote.known_subtotal)} · 待报价 {snapshot.quote.pending_count} 项</p><p>当前清单合计：{money(snapshot.quote.total_price)}</p><p>估价时间：{new Date(snapshot.quote.created_at).toLocaleString()}</p></>:<p>本交付未附估价快照。</p>}
    </section>
    {snapshot.space.rooms.map(r=><section key={r.id} className="hdelivery-room">
      <h2>{r.name}</h2><p>净高 {r.height} 米</p>
      <div className="hdelivery-plan"><HomeDesignCanvas space={snapshot.space} document={snapshot.document} roomId={r.id} mode="2d" selected={null} onSelect={()=>{}} showCeiling={false}/></div>
      <div className="hdelivery-table"><table><caption>材料与物件清单</caption><thead><tr><th>项目</th><th>材料</th><th>数量</th><th>估价</th></tr></thead><tbody>{snapshot.lines.filter(line=>line.room_id===r.id).map(line=>{
        const price=snapshot.quote?.lines.find(q=>q.entity_type===line.entity_type&&q.id===line.id);
        return <tr key={`${line.entity_type}-${line.id}`}><td>{line.name}</td><td>{line.material.name}</td><td>{line.quantity??"待确认"} {line.unit==="m2"?"平方米":"件"}</td><td>{price?.unit_price != null && <small>单价 {money(price.unit_price)}</small>}<div>{money(price?.total_price??null)}</div><HomeQuoteEvidence evidence={price?.rule_evidence} currency={snapshot.quote?.currency ?? "CNY"}/></td></tr>;
      })}</tbody></table></div>
      {!!snapshot.document.points?.filter(point=>point.room_id===r.id).length&&<><h3>已有点位</h3>{snapshot.document.points.filter(point=>point.room_id===r.id).map(point=><p key={point.id}>{point.name} · {pointLabels[point.kind]} · {point.confirmed?"已核对":"待现场核对"} · ({point.position.x}, {point.position.y}, {point.position.z}) 米</p>)}</>}
      {snapshot.document.objects.filter(object=>object.room_id===r.id&&(object.installation||object.clearance||object.point_requirement)).map(object=><div key={object.id}><h3>{object.name}的使用条件</h3>
        {object.installation&&<p>安装：{{floor:"落地",wall:"墙装",ceiling:"顶装"}[object.installation.kind]}{object.installation.wall_id?` · 墙 ${object.installation.wall_id}`:""}</p>}
        {object.clearance&&<p>预留（米）：前 {object.clearance.front}、后 {object.clearance.back}、左 {object.clearance.left}、右 {object.clearance.right}、上 {object.clearance.above} · {object.clearance.confirmed?"已核对使用要求":"待核对"}</p>}
        {object.point_requirement&&<p>关联点位：{snapshot.document.points?.find(point=>point.id===object.point_requirement!.point_id)?.name??"已失效"} · 最大直线距离 {object.point_requirement.max_distance_m} 米</p>}
      </div>)}
    </section>)}
    <section><h2>适用范围</h2><ul>{[...snapshot.limitations,...(snapshot.quote?.limitations??[])].map((text,i)=><li key={i}>{text}</li>)}</ul></section>
  </>;
}
