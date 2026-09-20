import { lazy,Suspense,useEffect,useMemo,useRef,useState,useSyncExternalStore,type FormEvent,type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft,Box,Check,ChevronDown,Download,Focus,History,Layers,Loader2,Map,Plus,Redo2,RefreshCw,Save,Trash2,Undo2,Upload,X } from "lucide-react";
import { getTaskSpace,saveTaskSpace,getTaskSpaceVersion,getTaskSpaceVersions } from "@/api/designApi";
import { SpatialEditor } from "@/lib/spatialEditor";
import { buildRoomWalls,distance,rectangleRoom,removeRoomWalls,removeSpatialRoom,roomArea,scaleSpatialDocument,spatialBounds,spatialId,validateSpatialDraft,updateSpatialRoom } from "@/lib/spatialGeometry";
import type { SpatialDocument,SpatialOpening,SpatialPoint,SpatialVersionList } from "@/types/spatial";
import type { RoomSource } from "@/types/roomModel";
import RoomSourcePreview from "@/components/workspace/RoomSourcePreview";
import { usePrivateImage } from "@/lib/usePrivateImage";
import "./spatial.css";
const SpatialCanvas3D=lazy(() => import("./SpatialCanvas3D"));
function Tool({ label,children,onClick,disabled,active }: {
  label: string;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
}) {
  return <button type="button" className={`sp-tool ${active? "active":""}`} title={label} aria-label={label} aria-pressed={active} onClick={onClick} disabled={disabled}>{children}</button>;
}
function NumberField({ label,name,value,min,max,disabled }: {
  label: string;
  name: string;
  value: number;
  step?: number;
  min?: number;
  max?: number;
  disabled?: boolean;
}) {
  return <label className="sp-field"><span>{label}</span><input name={name} type="number" step="any" min={min} max={max} defaultValue={value} required disabled={disabled} /></label>;
}
const number=(data: FormData,key: string) => Number(data.get(key));
function download(document: SpatialDocument,taskId: number,version: number) {
  const url=URL.createObjectURL(new Blob([JSON.stringify({ task_id: taskId,version,document },null,2)],{ type: "application/json" }));
  const link=window.document.createElement("a");
  link.href=url;
  link.download=`整屋空间-${taskId}-v${version}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
}
export default function WholeHomeWorkspace({ taskId,title,roomSource }: {
  taskId: number;
  title: string;
  roomSource?: RoomSource|null;
}) {
  const editor=useMemo(() => new SpatialEditor(taskId,{ get: getTaskSpace,save: saveTaskSpace },window.localStorage),[taskId]);
  const state=useSyncExternalStore(editor.subscribe,editor.getSnapshot);
  const [selection,setSelection]=useState<string|null>(null);
  const [mode,setMode]=useState<"2d"|"3d">("2d");
  const [focus,setFocus]=useState(false),[showWalls,setShowWalls]=useState(true);
  const [mobilePanel,setMobilePanel]=useState<"canvas"|"rooms"|"properties">("canvas");
  const [error,setError]=useState("");
  const [drawing,setDrawing]=useState<SpatialPoint[]|null>(null);
  const [wallId,setWallId]=useState("");
  const [versions,setVersions]=useState<SpatialVersionList|null>(null);
  const [historyBusy,setHistoryBusy]=useState(false);
  const [source,setSource]=useState<RoomSource|null>(null);
  const privateSource = usePrivateImage(source?.image_id);
  const [sourceError,setSourceError]=useState("");
  const [referenceBusy,setReferenceBusy]=useState(false),[showReference,setShowReference]=useState(true);
  const fileInput=useRef<HTMLInputElement>(null);
  const svgRef=useRef<SVGSVGElement>(null);
  const canvasRef=useRef<HTMLDivElement>(null);
  const [canvasSize,setCanvasSize]=useState({ width: 600,height: 500 });
  useEffect(() => {
    if(!canvasRef.current)
      return; const observer=new ResizeObserver(entries => {
        const rect=entries[0].contentRect; if(rect.width&&rect.height)
          setCanvasSize({ width: rect.width,height: rect.height });
      }); observer.observe(canvasRef.current); return () => observer.disconnect();
  },[]);
  useEffect(() => { void editor.load(); },[editor]);
  useEffect(() => {
    const prevent=(event: BeforeUnloadEvent) => {
      if(state.dirty) {
        event.preventDefault();
        event.returnValue="";
      }
    };
    window.addEventListener("beforeunload",prevent);
    return () => window.removeEventListener("beforeunload",prevent);
  },[state.dirty]);
  useEffect(() => {
    let active=true;
    setSource(null);
    setSourceError("");
    if(!state.document.source_image_id) {
      setSource(roomSource??null);
      return;
    }
    if(roomSource?.image_id===state.document.source_image_id) {
      setSource(roomSource);
      return;
    }
    if(state.document.source_image_id) {
      import("@/api/designApi").then(api => api.getTaskSpaceDraftSource(taskId,state.document.source_image_id!)).then(result => {
        if(active) {
          if(result?.image_id===state.document.source_image_id)
            setSource(result);
          else
            setSourceError("该草稿关联的原图尚未恢复");
        }
      }).catch(() => {
        if(active)
          setSourceError("原图信息读取失败");
      });
    }
    return () => { active=false; };
  },[taskId,state.version,state.document.source_image_id,roomSource]);
  const document=state.document;
  const selected=document.rooms.find(r => r.id===selection)??null;
  const roomWalls=document.walls.filter(w => selected&&w.room_ids.includes(selected.id));
  const activeWall=roomWalls.find(w => w.id===wallId)??roomWalls[0];
  const bounds=spatialBounds(focus&&selected? { ...document,rooms: [selected],image_reference: null }:document);
  const padding=Math.max(bounds.width,bounds.depth)*.12;
  const viewBox=`${bounds.minX-padding} ${bounds.minZ-padding} ${bounds.width+padding*2} ${bounds.depth+padding*2}`;
  const unit=Math.max(bounds.width,bounds.depth)/50;
  const pixelsPerUnit=Math.min(canvasSize.width/(bounds.width+padding*2),canvasSize.height/(bounds.depth+padding*2));
  const act=(operation: () => void) => {
    setError(""); try {
      operation();
    }
      catch(e) {
        setError(e instanceof Error? e.message:"修改失败");
      }
  };
  const change=(next: SpatialDocument) => act(() => editor.change(next));
  const select=(id: string) => { setSelection(id); setWallId(""); };
  const load=() => {
    if(!state.dirty||window.confirm("重新载入将丢弃本机未保存修改，是否继续？")) {
      setDrawing(null);
      void editor.load(true);
    }
  };
  const addRoom=(event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data=new FormData(event.currentTarget);
    act(() => {
      const room=rectangleRoom(spatialId(),String(data.get("name")),number(data,"x"),number(data,"z"),number(data,"width"),number(data,"depth"),number(data,"height"));
      editor.change({ ...document,rooms: [...document.rooms,room],scale_status: "unconfirmed" });
      select(room.id);
      setMobilePanel("canvas");
    });
  };
  const updateRoom=(event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if(!selected)
      return;
    const data=new FormData(event.currentTarget);
    const height=number(data,"height");
    const polygon=roomWalls.length? selected.polygon:selected.polygon.map((_,i) => ({ x: number(data,`x-${i}`),z: number(data,`z-${i}`) }));
    act(() => editor.change(updateSpatialRoom(document,{ ...selected,name: String(data.get("name")),height,polygon })));
  };
  const removeRoom=() => {
    if(selected&&window.confirm(`删除「${selected.name}」及其独有墙体、门窗？`)) {
      change(removeSpatialRoom(document,selected.id));
      setSelection(null);
    }
  };
  const finishDrawing=() => act(() => {
    if(!drawing||drawing.length<3)
      throw Error("至少需要三个轮廓点");
    const id=spatialId();
    editor.change({ ...document,scale_status: "unconfirmed",rooms: [...document.rooms,{ id,name: `房间 ${document.rooms.length+1}`,height: 2.8,polygon: drawing }] });
    setDrawing(null);
    select(id);
    setMobilePanel("properties");
  });
  const addOpening=(event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if(!activeWall)
      return;
    const data=new FormData(event.currentTarget);
    const opening: SpatialOpening={ id: spatialId(),wall_id: activeWall.id,type: String(data.get("type")) as SpatialOpening["type"],offset: number(data,"offset"),width: number(data,"width"),height: number(data,"height"),sill_height: number(data,"sill_height") };
    change({ ...document,openings: [...document.openings,opening] });
  };
  const readHistory=async (before?: number) => {
    setHistoryBusy(true);
    setError("");
    try {
      const page=await getTaskSpaceVersions(taskId,before);
      setVersions(old => before&&old? { ...page,versions: [...old.versions,...page.versions] }:page);
    }
    catch {
      setError("版本历史读取失败，请重试");
    }
    finally {
      setHistoryBusy(false);
    }
  };
  useEffect(() => {
    if(versions)
      void readHistory();
  },[state.version]);
  const registerReference=async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const width=number(new FormData(event.currentTarget),"reference_width");
    const url=privateSource.url;
    if(!url||!source)
      return;
    const before=editor.snapshot;
    setReferenceBusy(true);
    setError("");
    try {
      const image=new Image();
      image.src=url;
      await image.decode();
      if(editor.snapshot!==before)
        throw Error("读取期间草稿已变化，请重新设置底图");
      if(!image.naturalWidth||!image.naturalHeight)
        throw Error("底图无法读取");
      editor.change({ ...before.document,source_image_id: source.image_id,image_reference: { origin: { x: 0,z: 0 },width,depth: width*image.naturalHeight/image.naturalWidth },scale_status: "unconfirmed" });
      setMode("2d");
      setShowReference(true);
      setFocus(false);
      setMobilePanel("canvas");
    }
    catch(e) {
      setError(e instanceof Error? e.message:"底图无法读取");
    }
    finally {
      setReferenceBusy(false);
    }
  };
  const restore=async (version: number) => {
    if(!editor.editable||!window.confirm(`将版本 ${version} 载入当前草稿？保存后会生成新版本。`))
      return;
    const before=editor.snapshot;
    setHistoryBusy(true);
    try {
      const old=await getTaskSpaceVersion(taskId,version);
      if(editor.snapshot!==before)
        throw Error("读取期间草稿已变化，请重新选择历史版本");
      if(old.document)
        editor.change(old.document);
    }
    catch(e) {
      setError(e instanceof Error? e.message:"版本恢复失败");
    }
    finally {
      setHistoryBusy(false);
    }
  };
  const importFile=async (file: File|undefined) => {
    if(!file)
      return;
    act(() => {
      if(file.size>2000000)
        throw Error("空间文件不能超过 2 MB");
    });
    if(file.size>2000000)
      return;
    try {
      const parsed=JSON.parse(await file.text());
      const next=parsed.document??parsed;
      const invalid=validateSpatialDraft(next);
      if(invalid)
        throw Error(invalid);
      if(window.confirm("载入文件将替换当前草稿，是否继续？")) {
        editor.change(next);
        setSelection(null);
        setError("");
      }
    }
    catch(e) {
      setError(e instanceof Error? e.message:"空间文件无法读取");
    }
  };
  const statusLabel=state.status==="saving"? "正在保存":state.status==="loading"? "正在读取":state.status==="conflict"? "版本冲突":state.dirty? "有未保存修改":state.version? `已保存 · V${state.version}`:"尚未建立户型";
  return <div className="sp-workspace">
    <header className="sp-header">
      <div className="sp-heading"><Link to={`/design/${taskId}/workspace`} title="返回设计工作台" aria-label="返回设计工作台" className="sp-tool"><ArrowLeft size={18} /></Link><div><h1>{title} · 整屋户型</h1><p role="status">{statusLabel}</p></div></div>
      <div className="sp-actions"><Tool label="撤销" onClick={() => editor.undo()} disabled={!editor.editable||!state.canUndo}><Undo2 size={18} /></Tool><Tool label="重做" onClick={() => editor.redo()} disabled={!editor.editable||!state.canRedo}><Redo2 size={18} /></Tool><Tool label="重新载入" onClick={load} disabled={state.status==="saving"}><RefreshCw size={17} /></Tool><Tool label="下载空间草稿" onClick={() => download(document,taskId,state.version)}><Download size={17} /></Tool>
        <button className="sp-primary" onClick={() => void editor.save()} disabled={!state.dirty||!["ready","invalid","error"].includes(state.status)}>{state.status==="saving"? <Loader2 size={16} className="animate-spin" />:<Save size={16} />}保存</button>
        {state.version>0&&!state.dirty&&state.status==="ready"&&document.scale_status==="confirmed"?
          <Link className="sp-secondary" to={`/design/${taskId}/home-design`}>进入家装设计</Link>:
          <button className="sp-secondary" disabled title="请先确认户型尺度并保存">进入家装设计</button>}
      </div>
    </header>
    {(error||state.message||state.storageWarning)&&<div className={`sp-message ${error||["error","invalid","conflict","load-error"].includes(state.status)? "error":""}`} role={error||state.status!=="ready"? "alert":"status"}>{error||state.message}{state.storageWarning&&<span>{state.storageWarning}</span>}{state.status==="load-error"&&<button onClick={() => void editor.load()}>重试读取</button>}{state.status==="error"&&<button onClick={() => void editor.save()}>重试保存</button>}{state.status==="conflict"&&<button onClick={load}>重新载入</button>}</div>}
    <nav className="sp-mobile-tabs" aria-label="整屋工作区">{([['rooms','房间'],['canvas','画布'],['properties','属性']] as const).map(([id,label]) => <button key={id} onClick={() => setMobilePanel(id)} aria-pressed={mobilePanel===id}>{label}</button>)}</nav>
    <div className="sp-body">
      <aside className={`sp-sidebar sp-room-list ${mobilePanel==="rooms"? "mobile-open":""}`} aria-label="房间与资料">
        <div className="sp-section-heading"><h2>房间</h2><span>{document.rooms.length} 间 · {document.rooms.reduce((s,r) => s+roomArea(r),0).toFixed(1)} m²</span></div>
        <div className="sp-rooms">{document.rooms.map(r => <button key={r.id} aria-pressed={r.id===selection} onClick={() => select(r.id)}><span>{r.name}</span><small>{roomArea(r).toFixed(1)} m²</small></button>)}</div>
        <details open={document.rooms.length===0||undefined}><summary><Plus size={15} />添加房间</summary><form onSubmit={addRoom} className="sp-form"><fieldset disabled={!editor.editable}>
          <label className="sp-field"><span>新房间名称</span><input name="name" defaultValue="客厅" maxLength={100} required /></label>
          <div className="sp-pair"><NumberField label="起点 X (m)" name="x" value={document.rooms.length? bounds.minX+bounds.width:0} /><NumberField label="起点 Z (m)" name="z" value={0} /><NumberField label="宽 (m)" name="width" value={4} min={.01} /><NumberField label="深 (m)" name="depth" value={3} min={.01} /></div>
          <NumberField label="层高 (m)" name="height" value={2.8} min={1.81} max={8} /><button className="sp-primary" type="submit"><Plus size={15} />建立房间</button>
        </fieldset></form></details>
        <button className="sp-secondary sp-wide" disabled={!editor.editable} onClick={() => { setDrawing([]); setMode("2d"); setMobilePanel("canvas"); }}>描绘房间轮廓</button>
        <details><summary><Map size={15} />原始资料</summary><div className="sp-form">{source? <RoomSourcePreview source={source} />:<p>{sourceError||"尚未关联原图"}</p>}<Link to={`/design/${taskId}/workspace`}>上传或更换原图</Link>{roomSource&&document.source_image_id!==roomSource.image_id&&<button className="sp-secondary" disabled={!editor.editable} onClick={() => {
          if(window.confirm("将当前原图关联到这份空间草稿？"))
            change({ ...document,source_image_id: roomSource.image_id,image_reference: null,scale_status: "unconfirmed" });
        }}>关联当前原图</button>}
          {source&&<form onSubmit={event => void registerReference(event)} className="sp-reference-form"><fieldset disabled={!editor.editable||referenceBusy}><label className="sp-field"><span>底图覆盖宽度 (m)</span><input name="reference_width" type="number" step="any" min="0.01" max="10000" required defaultValue={document.image_reference?.width} /></label><button type="submit" className="sp-secondary">{referenceBusy? "正在读取…":"设置描绘底图"}</button></fieldset></form>}
          {document.image_reference&&<label className="sp-checkbox"><input type="checkbox" checked={showReference} onChange={event => setShowReference(event.target.checked)} />显示描绘底图</label>}
        </div></details>
        <details onToggle={event => {
          if(event.currentTarget.open)
            void readHistory();
        }}><summary><History size={15} />版本历史</summary><div className="sp-history">{versions?.versions.map(v => <button key={v.version} disabled={!editor.editable||historyBusy} onClick={() => void restore(v.version)}><span>V{v.version} · {v.room_count} 间</span><small>{v.created_at? new Date(v.created_at).toLocaleString():""}</small></button>)}{versions&&!versions.versions.length&&<p>尚无保存记录</p>}{historyBusy&&<p>正在读取…</p>}{versions?.next_before_version&&<button onClick={() => void readHistory(versions.next_before_version!)}>更多版本<ChevronDown size={14} /></button>}</div></details>
        <button className="sp-secondary sp-wide" disabled={!editor.editable} onClick={() => fileInput.current?.click()}><Upload size={15} />载入空间文件</button><input ref={fileInput} type="file" accept="application/json,.json" hidden onChange={event => { void importFile(event.target.files?.[0]); event.target.value=""; }} />
      </aside>
      <main className={`sp-main ${mobilePanel==="canvas"? "mobile-open":""}`}>
        <div className="sp-canvas-toolbar"><div className="sp-segment" aria-label="画布模式"><button onClick={() => setMode("2d")} aria-pressed={mode==="2d"}><Map size={15} />2D</button><button onClick={() => { setDrawing(null); setMode("3d"); }} aria-pressed={mode==="3d"}><Box size={15} />3D</button></div><div className="sp-actions"><Tool label={focus? "查看整屋":"聚焦选中房间"} disabled={!selected} active={focus} onClick={() => setFocus(!focus)}><Focus size={17} /></Tool><Tool label="显示墙体" active={showWalls} onClick={() => setShowWalls(!showWalls)}><Layers size={17} /></Tool></div><span className={`sp-scale ${document.scale_status==="confirmed"? "confirmed":""}`}>{document.scale_status==="confirmed"? "尺度已确认":"尺度待确认"}</span></div>
        {drawing&&<div className="sp-drawing"><span>轮廓点 {drawing.length}</span><button disabled={drawing.length<3} onClick={finishDrawing}><Check size={16} />完成轮廓</button><Tool label="撤销轮廓点" onClick={() => setDrawing(drawing.slice(0,-1))}><Undo2 size={16} /></Tool><Tool label="取消描绘" onClick={() => setDrawing(null)}><X size={16} /></Tool></div>}
        <div className="sp-canvas" ref={canvasRef}>
          {mode==="2d"? <svg ref={svgRef} viewBox={viewBox} aria-label="整屋平面画布" role="img" onClick={event => {
            if(!drawing||!editor.editable||!svgRef.current)
              return; const svg=svgRef.current,ctm=svg.getScreenCTM(); if(!ctm)
              return; const p=new DOMPoint(event.clientX,event.clientY).matrixTransform(ctm.inverse()); setDrawing([...drawing,{ x: Math.round(p.x*20)/20,z: Math.round(p.y*20)/20 }]);
          }} className={drawing? "drawing":""}>
            <defs><pattern id={`sp-grid-${taskId}`} width="1" height="1" patternUnits="userSpaceOnUse"><path d="M 1 0 L 0 0 0 1" fill="none" stroke="#dce3df" strokeWidth={unit*.025} /></pattern></defs>
            <rect x={bounds.minX-padding} y={bounds.minZ-padding} width={bounds.width+padding*2} height={bounds.depth+padding*2} fill={`url(#sp-grid-${taskId})`} />
            {document.image_reference&&showReference&&privateSource.url&&source?.image_id===document.source_image_id&&<image href={privateSource.url} x={document.image_reference.origin.x} y={document.image_reference.origin.z} width={document.image_reference.width} height={document.image_reference.depth} preserveAspectRatio="none" opacity={.6} onError={() => setSourceError("描绘底图暂不可用")} />}
            {document.rooms.map((r,i) => <g key={r.id} onClick={event => {
              if(!drawing) {
                event.stopPropagation();
                select(r.id);
              }
            }}><polygon points={r.polygon.map(p => `${p.x},${p.z}`).join(" ")} fill={r.id===selection? "#d2e8dc":["#e8ece8","#eeebe2","#e2eaf0","#eee3e8"][i%4]} stroke={r.id===selection? "#387660":"#9daea3"} strokeWidth={unit*.12} /><text x={r.polygon.reduce((s,p) => s+p.x,0)/r.polygon.length} y={r.polygon.reduce((s,p) => s+p.z,0)/r.polygon.length} textAnchor="middle" fontSize={12/pixelsPerUnit} fill="#33483e">{r.name.length>12? `${r.name.slice(0,11)}…`:r.name}</text></g>)}
            {showWalls&&document.walls.map(w => <line key={w.id} x1={w.start.x} y1={w.start.z} x2={w.end.x} y2={w.end.z} stroke={w.id===activeWall?.id? "#326e59":"#52665b"} strokeWidth={w.thickness} />)}
            {document.openings.map(o => {
              const w=document.walls.find(w => w.id===o.wall_id); if(!w)
                return null; const length=distance(w.start,w.end),a=o.offset/length,b=(o.offset+o.width)/length; return <line key={o.id} x1={w.start.x+(w.end.x-w.start.x)*a} y1={w.start.z+(w.end.z-w.start.z)*a} x2={w.start.x+(w.end.x-w.start.x)*b} y2={w.start.z+(w.end.z-w.start.z)*b} stroke={o.type==="window"? "#5a9cb9":"#c3934e"} strokeWidth={w.thickness*1.3} />;
            })}
            {selected&&!drawing&&selected.polygon.map((p,i) => <g key={i}><circle cx={p.x} cy={p.z} r={3/pixelsPerUnit} fill="#2d7556" /><text x={p.x+6/pixelsPerUnit} y={p.z-6/pixelsPerUnit} fontSize={10/pixelsPerUnit} fill="#2d7556">{i+1}</text></g>)}
            {drawing&&<><polyline points={drawing.map(p => `${p.x},${p.z}`).join(" ")} fill="none" stroke="#297252" strokeWidth={unit*.13} />{drawing.map((p,i) => <circle key={i} cx={p.x} cy={p.z} r={unit*.2} fill="#297252" />)}</>}
          </svg>:<Suspense fallback={<p className="sp-loading">正在加载三维空间…</p>}><SpatialCanvas3D document={document} selected={selection} focus={focus} showWalls={showWalls} onSelect={select} /></Suspense>}
          {!document.rooms.length&&!drawing&&<div className="sp-empty"><Map size={32} /><h2>建立你的整屋户型</h2><button className="sp-primary" onClick={() => setMobilePanel("rooms")}><Plus size={16} />添加房间</button></div>}
        </div>
        <footer className="sp-canvas-footer"><span>{document.rooms.length} 个房间 · {document.walls.length} 段墙 · {document.openings.length} 处门窗</span><span>m</span></footer>
      </main>
      <aside className={`sp-sidebar sp-properties ${mobilePanel==="properties"? "mobile-open":""}`} aria-label="空间属性">
        <div className="sp-section-heading"><h2>{selected?.name??"空间属性"}</h2>{selected&&<Tool label="删除房间" onClick={removeRoom} disabled={!editor.editable}><Trash2 size={16} /></Tool>}</div>
        {selected? <form className="sp-form" onSubmit={updateRoom} key={JSON.stringify(selected)}><fieldset disabled={!editor.editable}>
          <label className="sp-field"><span>房间名称</span><input name="name" defaultValue={selected.name} maxLength={100} required /></label><NumberField label="房间层高 (m)" name="height" value={selected.height} min={1.81} max={8} />
          <details open><summary>轮廓坐标 (m)</summary><div className="sp-vertices">{selected.polygon.map((p,i) => <div key={i}><span>{i+1}</span><input aria-label={`顶点 ${i+1} X`} name={`x-${i}`} type="number" step="0.01" defaultValue={p.x} disabled={!!roomWalls.length} /><input aria-label={`顶点 ${i+1} Z`} name={`z-${i}`} type="number" step="0.01" defaultValue={p.z} disabled={!!roomWalls.length} /><Tool label={`删除顶点 ${i+1}`} disabled={!!roomWalls.length||selected.polygon.length<=3} onClick={() => change({ ...document,scale_status: "unconfirmed",rooms: document.rooms.map(r => r.id===selected.id? { ...r,polygon: r.polygon.filter((_,j) => i!==j) }:r) })}><X size={13} /></Tool></div>)}</div>
            {!roomWalls.length&&<button className="sp-secondary" type="button" onClick={() => { const points=selected.polygon,a=points[points.length-1],b=points[0]; change({ ...document,rooms: document.rooms.map(r => r.id===selected.id? { ...r,polygon: [...points,{ x: (a.x+b.x)/2,z: (a.z+b.z)/2 }] }:r),scale_status: "unconfirmed" }); }}><Plus size={14} />增加轮廓点</button>}
            {!!roomWalls.length&&<button className="sp-secondary" type="button" onClick={() => {
              if(window.confirm("重绘边界需要移除本房间的墙体关联及独有门窗。是否继续？"))
                change(removeRoomWalls(document,selected.id));
            }}>重绘边界</button>}</details><button className="sp-primary" type="submit">应用房间属性</button>
        </fieldset></form>:<p className="sp-hint">尚未选择房间</p>}
        {selected&&<details open><summary><Layers size={15} />墙体与门窗</summary><form className="sp-form" onSubmit={event => { event.preventDefault(); const d=new FormData(event.currentTarget); act(() => editor.change(buildRoomWalls(document,selected.id,number(d,"thickness")))); }}><fieldset disabled={!editor.editable}><NumberField label="墙厚 (m)" name="thickness" value={roomWalls[0]?.thickness??.12} min={.01} max={1} step={.01} /><button className="sp-secondary" type="submit">按轮廓建立墙体</button></fieldset></form>
          {!!roomWalls.length&&<div className="sp-form"><label className="sp-field"><span>当前墙段</span><select aria-label="当前墙段" value={activeWall?.id??""} onChange={event => setWallId(event.target.value)}>{roomWalls.map((w,i) => <option key={w.id} value={w.id}>墙 {i+1} · {distance(w.start,w.end).toFixed(2)} m{w.room_ids.length>1? " · 共享":""}</option>)}</select></label>
            {activeWall&&<form key={`wall-${JSON.stringify(activeWall)}`} onSubmit={event => {
              event.preventDefault(); const data=new FormData(event.currentTarget);
              change({ ...document,scale_status: "unconfirmed",walls: document.walls.map(w => w.id===activeWall.id? { ...w,height: number(data,"height"),thickness: number(data,"thickness") }:w) });
            }}><fieldset disabled={!editor.editable}><div className="sp-pair"><NumberField label="墙段高度 (m)" name="height" value={activeWall.height} min={.01} max={Math.min(...activeWall.room_ids.map(id => document.rooms.find(r => r.id===id)!.height))} /><NumberField label="墙段厚度 (m)" name="thickness" value={activeWall.thickness} min={.01} max={1} /></div><button className="sp-secondary" type="submit">应用墙体属性</button></fieldset></form>}
            <form onSubmit={addOpening} key={activeWall?.id}><fieldset disabled={!editor.editable}><label className="sp-field"><span>开口类型</span><select name="type" aria-label="开口类型"><option value="door">门</option><option value="window">窗</option><option value="passage">通道</option></select></label><div className="sp-pair"><NumberField label="起点偏移 (m)" name="offset" value={.3} min={0} /><NumberField label="开口宽 (m)" name="width" value={.9} min={.01} /><NumberField label="开口高 (m)" name="height" value={2.1} min={.01} /><NumberField label="窗台高 (m)" name="sill_height" value={0} min={0} /></div><button className="sp-primary" type="submit"><Plus size={14} />添加门窗</button></fieldset></form>
            {document.openings.filter(o => o.wall_id===activeWall?.id).map(o => <details key={o.id}><summary>{o.type==="door"? "门":o.type==="window"? "窗":"通道"} · {o.width} × {o.height} m</summary><form key={JSON.stringify(o)} onSubmit={event => { event.preventDefault(); const d=new FormData(event.currentTarget); change({ ...document,openings: document.openings.map(item => item.id===o.id? { ...item,offset: number(d,"offset"),width: number(d,"width"),height: number(d,"height"),sill_height: number(d,"sill_height") }:item) }); }}><fieldset disabled={!editor.editable}><div className="sp-pair"><NumberField label="偏移 (m)" name="offset" value={o.offset} min={0} /><NumberField label="宽度 (m)" name="width" value={o.width} min={.01} /><NumberField label="高度 (m)" name="height" value={o.height} min={.01} /><NumberField label="离地 (m)" name="sill_height" value={o.sill_height} min={0} /></div><div className="sp-actions"><button type="submit" className="sp-secondary">应用</button><Tool label="删除门窗" onClick={() => change({ ...document,openings: document.openings.filter(item => item.id!==o.id) })}><Trash2 size={14} /></Tool></div></fieldset></form></details>)}
          </div>}
        </details>}
        <details open><summary><Focus size={15} />整屋尺度</summary><div className="sp-form"><form onSubmit={event => { event.preventDefault(); const data=new FormData(event.currentTarget); act(() => editor.change(scaleSpatialDocument(document,number(data,"actual")/number(data,"drawing")))); }}><fieldset disabled={!editor.editable||!document.rooms.length}><div className="sp-pair"><NumberField label="图上长度 (m)" name="drawing" value={1} min={.0001} step={.01} /><NumberField label="实测长度 (m)" name="actual" value={1} min={.0001} step={.01} /></div><button className="sp-secondary" type="submit">校准整屋比例</button></fieldset></form>
          <label className="sp-checkbox"><input type="checkbox" checked={document.scale_status==="confirmed"} disabled={!editor.editable||!document.rooms.length} onChange={event => change({ ...document,scale_status: event.target.checked? "confirmed":"unconfirmed" })} />已核对实际尺寸</label>
        </div></details>
      </aside>
    </div>
  </div>;
}
