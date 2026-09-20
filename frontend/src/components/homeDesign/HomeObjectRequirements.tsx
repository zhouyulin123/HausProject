import { useState } from "react";
import type { HomeObject, HomePoint } from "@/types/homeDesign";
import type { SpatialDocument } from "@/types/spatial";

export default function HomeObjectRequirements({object,space,points}: {object: HomeObject; space: SpatialDocument; points: HomePoint[]}) {
  const [kind,setKind] = useState(object.installation?.kind ?? "");
  const [clearance,setClearance] = useState(!!object.clearance);
  const [point,setPoint] = useState(object.point_requirement?.point_id ?? "");
  return <details className="hd-requirements"><summary>安装与使用约束</summary>
    <label>安装方式<select name="installation" value={kind} onChange={e => setKind(e.target.value)}>
      <option value="">待确认</option><option value="floor">落地</option>
      {!object.asset_id && <><option value="wall">墙装</option><option value="ceiling">顶装</option></>}
    </select></label>
    {kind === "wall" && <label>安装宿主墙<select name="installation_wall" required defaultValue={object.installation?.wall_id ?? ""}>
      <option value="">请选择墙体</option>{space.walls.map(w => <option key={w.id} value={w.id}>{space.rooms.filter(r => w.room_ids.includes(r.id)).map(r => r.name).join(" / ")} · {w.id}</option>)}
    </select></label>}
    <label className="hd-check"><input type="checkbox" name="clearance_enabled" checked={clearance} onChange={e => setClearance(e.target.checked)}/>设置使用预留空间</label>
    {clearance && <><div className="hd-fields">{([ ["front","前方"],["back","后方"],["left","左侧"],["right","右侧"],["above","上方"] ] as const).map(([key,label]) => <label key={key}>{label}（米）<input name={`clearance_${key}`} type="number" min="0" max="10" step="any" required defaultValue={object.clearance?.[key] ?? ""}/></label>)}</div>
      <label className="hd-check"><input type="checkbox" name="clearance_confirmed" defaultChecked={object.clearance?.confirmed ?? false}/>已核对使用要求</label></>}
    <label>关联已有点位<select name="point_requirement" value={point} onChange={e => setPoint(e.target.value)}>
      <option value="">未关联</option>{point && !points.some(p => p.id === point) && <option value={point}>已失效点位 · {point}</option>}{points.map(p => <option key={p.id} value={p.id}>{p.name} · {space.rooms.find(r => r.id === p.room_id)?.name ?? "房间已失效"}</option>)}
    </select></label>
    {point && <label>最大连接距离（米）<input type="number" name="point_distance" min="0" max="100" step="any" required defaultValue={object.point_requirement?.max_distance_m ?? ""}/></label>}
  </details>;
}
