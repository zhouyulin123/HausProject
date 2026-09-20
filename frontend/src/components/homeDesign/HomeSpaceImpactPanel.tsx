import { useState, useSyncExternalStore, type FormEvent } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import type { HomeDesignEditor } from "@/lib/homeDesignEditor";
import type { HomeSpaceImpact } from "@/types/homeDesign";

function ReferenceRepair({ impact, issue, disabled, onResolve, onPoint }: {
  impact: HomeSpaceImpact;
  issue: HomeSpaceImpact["reference_issues"][number];
  disabled: boolean;
  onResolve: (action: {roomId: string; wallId?: string} | "delete") => void;
  onPoint: (id: string | null) => void;
}) {
  const [roomId, setRoomId] = useState("");
  const [pointId, setPointId] = useState("");
  const entity = issue.entity_type === "object" ? impact.candidate_document.objects.find(o => o.id === issue.entity_id) : issue.entity_type === "point" ? impact.candidate_document.points?.find(p=>p.id===issue.entity_id) : impact.candidate_document.surfaces.find(s => s.id === issue.entity_id);
  if (issue.entity_type === "object" && ["point_missing", "point_room_mismatch"].includes(issue.code)) return <article className="hd-impact-issue">
    <strong>{entity && "name" in entity ? entity.name : issue.entity_id}</strong><p>{issue.message}</p>
    <fieldset disabled={disabled}>
      <label>重新关联点位<select value={pointId} onChange={event => setPointId(event.target.value)}><option value="">请选择同房间点位</option>{impact.candidate_document.points?.filter(point => point.room_id === entity?.room_id).map(point => <option key={point.id} value={point.id}>{point.name}</option>)}</select></label>
      <button disabled={!pointId} onClick={() => onPoint(pointId)}>确认点位并重新检查</button>
      <button onClick={() => {if(window.confirm("解除候选物件的点位关联？原方案保持不变。")) onPoint(null);}}>解除点位关联</button>
    </fieldset>
  </article>;
  const wallRequired = entity && (("kind" in entity && entity.kind === "wall") || ("installation" in entity && entity.installation?.kind === "wall"));
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    onResolve({roomId, wallId: wallRequired ? String(data.get("wall")) : undefined});
  };
  return <article className="hd-impact-issue">
    <strong>{entity && "name" in entity ? entity.name : entity && "material" in entity ? entity.material.name : issue.entity_id}</strong>
    <p>{issue.message}</p>
    <form onSubmit={submit}><fieldset disabled={disabled}>
      <label>迁入房间<select required value={roomId} onChange={e => setRoomId(e.target.value)}><option value="">请选择房间</option>{impact.target_space.rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
      {wallRequired && <label>目标墙体<select key={roomId} name="wall" required defaultValue=""><option value="">请选择墙体</option>{impact.target_space.walls.filter(w => w.room_ids.includes(roomId)).map(w => <option key={w.id} value={w.id}>{w.id}</option>)}</select></label>}
      <button type="submit">确认归属并重新检查</button>
      <button type="button" onClick={() => {if(window.confirm("从候选方案移除此项？当前方案保持不变。")) onResolve("delete");}}><Trash2 size={16}/>从候选移除</button>
    </fieldset></form>
  </article>;
}

export default function HomeSpaceImpactPanel({editor}: {editor: HomeDesignEditor}) {
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot);
  const [error,setError] = useState("");
  const impact = state.impact;
  return <section className="hd-space-impact">
    <p>当前绑定户型 V{state.document?.space_version}</p>
    <button disabled={!editor.editable || state.impactBusy} onClick={() => {setError("");void editor.previewSpaceImpact();}}><RefreshCw size={16}/>{state.impactBusy ? "检查中…" : "检查最新户型"}</button>
    {(state.impactError || error) && <p role="alert">{error || state.impactError}</p>}
    {impact && <>
      <h3>户型 V{impact.source_space_version} → V{impact.target_space_version}</h3>
      {!impact.changes.length && <p>空间结构没有变化</p>}
      <ul>{impact.changes.map((c,i) => <li key={i}>{({room:"房间",wall:"墙体",opening:"门窗",space:"空间"})[c.entity_type]} · {c.entity_id} · {({added:"新增",removed:"删除",modified:"修改"})[c.change]}</li>)}</ul>
      {impact.reference_issues.map(issue => <ReferenceRepair key={`${issue.entity_type}-${issue.entity_id}-${issue.code}`} impact={impact} issue={issue} disabled={!editor.editable || state.impactBusy} onPoint={pointId => {setError("");void editor.resolveSpacePoint(issue.entity_id,pointId).catch(e => setError(e instanceof Error ? e.message : "处理失败"));}} onResolve={action => {
        setError("");
        void editor.resolveSpaceReference(issue.entity_type,issue.entity_id,action).catch(e => setError(e instanceof Error ? e.message : "处理失败"));
      }}/>)}
      {impact.validation?.issues.map((issue,i) => <p key={i} role="status">{issue.message}</p>)}
      <button className="hd-save" disabled={!editor.editable || state.impactBusy || !!state.impactError || !impact.can_apply || !!impact.reference_issues.length} onClick={() => {
        if(window.confirm("载入新户型与候选方案为未保存草稿？可撤销，保存后形成新版本。")) editor.applySpaceImpact();
      }}>载入新户型草稿</button>
    </>}
  </section>;
}
