import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import type { HomeDesignDocument } from "@/types/homeDesign";
import type { SpatialDocument } from "@/types/spatial";
import { pointFromForm, pointLabels } from "./homeDesignFields";

export default function HomePointsPanel({document,space,disabled,selected,onSelect,onChange}: {document: HomeDesignDocument;space:SpatialDocument;disabled:boolean;selected:string|null;onSelect:(id:string|null)=>void;onChange:(d:HomeDesignDocument)=>void}) {
  const [creating,setCreating]=useState(false),[error,setError]=useState("");
  const point=(document.points ?? []).find(p => p.id === selected);
  useEffect(()=>{if(selected)setCreating(false);},[selected]);
  const submit=(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault();
    try {
      const next=pointFromForm(new FormData(event.currentTarget),creating?crypto.randomUUID():point!.id);
      onChange({...document,points:[...(document.points ?? []).filter(p => p.id !== next.id),next]});
      setCreating(false);onSelect(next.id);setError("");
    } catch(e){setError(e instanceof Error ? e.message : "点位修改失败");}
  };
  return <section>
    <button className="hd-add" disabled={disabled || (document.points?.length ?? 0)>=200} onClick={()=>{setCreating(true);onSelect(null);}}><Plus size={16}/>添加已有点位</button>
    <div className="hd-list">{document.points?.map(p=><button key={p.id} aria-pressed={selected===p.id} onClick={()=>{setCreating(false);onSelect(p.id);}}>{p.name}<small>{pointLabels[p.kind]} · {p.confirmed?"已核对":"待核对"}</small></button>)}</div>
    {error && <p role="alert">{error}</p>}
    {(creating || point) && <form key={creating?"new":JSON.stringify(point)} onSubmit={submit}><fieldset disabled={disabled}>
      <label>点位名称<input name="name" required maxLength={100} defaultValue={creating?"":point?.name}/></label>
      <label>点位类型<select name="kind" defaultValue={creating?"socket":point?.kind}>{Object.entries(pointLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      <label>所在房间<select name="room" required defaultValue={creating?"":point?.room_id}><option value="">请选择房间</option>{space.rooms.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      <div className="hd-fields">{([ ["x","全局 X"],["z","全局 Z"],["y","离地高度"] ] as const).map(([key,label])=><label key={key}>{label}（米）<input type="number" name={key} required step="any" min={key==="y"?0:-10000} max={key==="y"?8:10000} defaultValue={creating?"":point?.position[key]}/></label>)}</div>
      <label className="hd-check"><input type="checkbox" name="confirmed" defaultChecked={!creating && !!point?.confirmed}/>已按现场资料核对</label>
      <button className="hd-save" type="submit">保存点位到草稿</button>
      {!creating && point && <button type="button" onClick={()=>{if(window.confirm("删除此点位？相关物件的关联将保留为待修正，不会自动替换。")){onChange({...document,points:(document.points ?? []).filter(p=>p.id!==point.id)});onSelect(null);}}}><Trash2 size={16}/>删除点位</button>}
      {creating && <button type="button" onClick={()=>setCreating(false)}>取消添加</button>}
    </fieldset></form>}
  </section>;
}
