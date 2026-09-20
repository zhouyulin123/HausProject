import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Calculator, RefreshCw } from "lucide-react";
import { createHomeQuote, getHomeQuotes } from "@/api/homeDesignApi";
import { HomeQuoteController } from "@/lib/homeQuote";
import HomeQuoteEvidence from "./HomeQuoteEvidence";

const reasons:Record<string,string>={no_verified_price_binding:"尚未绑定核验价格",product_missing:"商品不存在",product_version_changed:"商品版本已更新",price_invalid:"价格无效",price_requires_selection:"规格价格待选择",not_verified:"商品未核验",region_unavailable:"当前地区不可用",out_of_stock:"库存不足",price_expired:"价格已过期"};
Object.assign(reasons,{inactive:"商品已停用",public_reference:"公开参考商品，不能作为正式报价",provenance_unverified:"商业来源待核验",source_name_missing:"来源名称缺失",source_reference_missing:"来源凭证缺失",source_retrieved_at_missing:"来源采集时间缺失",source_retrieved_at_future:"来源时间异常",price_observed_at_missing:"价格采集时间缺失",price_observed_at_future:"价格采集时间异常",verification_required:"待商业审核",verification_rejected:"商业审核未通过",verification_expired:"商业审核已过期",verification_invalid:"审核状态无效",verified_at_missing:"审核时间缺失",verified_at_future:"审核时间异常",verified_by_missing:"审核人员缺失",data_version_unverified:"数据版本待核验",availability_unknown:"供货情况未知",lead_time_unknown:"交期未知",availability_invalid:"供货状态无效",insufficient_stock:"库存数量不足",price_validity_unknown:"价格有效期未知",price_not_started:"价格尚未生效",region_unknown:"服务地区未知",region_required:"需要指定地区",dimensions_missing:"尺寸资料缺失",dimensions_exceeded:"尺寸超出限制",budget_exceeded:"超出预算"});
Object.assign(reasons,{surface_scale_unconfirmed:"空间尺度尚未确认",surface_quantity_unavailable:"表面数量暂不可计算",quote_rule_required:"尚未绑定材料计价规则",quote_rule_missing:"材料计价规则不存在",quote_rule_inactive:"材料计价规则已停用",quote_rule_version_invalid:"材料计价规则版本无效",quote_rule_unit_unsupported:"材料计价单位暂不支持",quote_rule_price_invalid:"材料单价无效",quote_rule_metadata_invalid:"材料规则信息不完整",quote_rule_region_invalid:"材料规则地区配置无效",quote_rule_region_mismatch:"材料规则不适用于当前地区"});
export default function HomeQuotePanel({taskId,version,dirty}:{taskId:number;version:number;dirty:boolean}) {
  const controller=useMemo(()=>new HomeQuoteController(taskId,version,{create:createHomeQuote,list:getHomeQuotes},window.localStorage),[taskId,version]);
  const state=useSyncExternalStore(controller.subscribe,controller.getSnapshot);
  const [region,setRegion]=useState("");
  useEffect(()=>{void controller.load();return()=>controller.dispose();},[controller]);
  const quote=state.selected?.snapshot;
  const money=(value:number|null|undefined)=>value==null?"待报价":`${value.toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2})} ${quote?.currency ?? "CNY"}`;
  return <section className="hd-quote">
    <h3>分项估价 · 家装 V{version}</h3>
    <label>地区代码<input aria-label="估价地区代码" value={region} placeholder="CN-SH" maxLength={32} onChange={e=>setRegion(e.target.value)} disabled={state.busy || !!state.pending}/></label>
    <button disabled={dirty || version<1 || state.busy || !!state.pending || !region} onClick={()=>void controller.create(region)}><Calculator size={16}/>创建此版本估价</button>
    <button disabled={state.busy} onClick={()=>void controller.load()}><RefreshCw size={16}/>刷新估价历史</button>
    {dirty && <p role="status">草稿尚未保存，暂不能创建估价。</p>}
    {state.pending && <div role="status"><p>待重试：家装 V{state.pending.home_version} · {state.pending.region}</p><button disabled={dirty || state.busy} onClick={()=>void controller.retry()}>重试原估价请求</button></div>}
    {state.busy && <p role="status">正在读取估价…</p>}
    {state.error && <p role="alert">{state.error}</p>}
    {!!state.items.length && <label>估价历史<select aria-label="估价历史" value={state.selected?.id ?? ""} onChange={e=>controller.select(Number(e.target.value))}>{state.items.map(item=><option key={item.id} value={item.id}>#{item.id} · {item.snapshot.region} · {new Date(item.snapshot.created_at).toLocaleString()}</option>)}</select></label>}
    {state.next && <button disabled={state.busy} onClick={()=>void controller.load(true)}>更多估价记录</button>}
    {quote && <>
      <p>{quote.region} · {new Date(quote.created_at).toLocaleString()} · 空间 V{quote.space_version}</p>
      <strong>已知小计：{money(quote.known_subtotal)}</strong>
      <p>待报价：{quote.pending_count} 项</p>
      <p>当前清单合计：{money(quote.total_price)}</p>
      {(quote.validation?.valid === false || quote.scale_status !== "confirmed") && <p role="status">{quote.scale_status !== "confirmed" ? "尺度待确认" : "方案存在待修正问题"}</p>}
      {!!quote.validation?.issues.length && <details><summary>方案检查结果</summary>{quote.validation.issues.map((issue,i)=><p key={i}>{issue.message}</p>)}</details>}
      <details><summary>估价明细（{quote.lines.length} 项）</summary>{quote.lines.map(line=><article key={`${line.entity_type}-${line.id}`}>
        <strong>{line.room_name} · {line.name}</strong><p>{line.quantity ?? "—"} {line.unit==="m2"?"平方米":"件"} · 单价 {money(line.unit_price)} · {money(line.total_price)}</p>
        {line.source_data_version && <small>计价数据 {line.source_data_version} · 规则 V{line.source_version}</small>}
        <HomeQuoteEvidence evidence={line.rule_evidence} currency={quote.currency}/>
        {!!line.reasons.length && <small>{line.reasons.map(code=>reasons[code] ?? code).join("、")}</small>}
      </article>)}</details>
      <ul>{quote.limitations.map(text=><li key={text}>{text}</li>)}</ul>
    </>}
  </section>;
}
