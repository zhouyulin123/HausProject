import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from "react";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Save,
  Undo2,
  Redo2,
  History,
  RefreshCw,
  Download,
  Plus,
  Trash2,
  SlidersHorizontal,
  Layers,
  Box,
  Map,
  X,
  MapPin,
} from "lucide-react";
import {
  getHomeDesign,
  saveHomeDesign,
  getHomeDesignVersion,
  getHomeDesignVersions,
  getHomeAsset,
  getHomeAssetOptions,
  freezeHomeAsset,
  previewHomeSpaceImpact,
} from "@/api/homeDesignApi";
import {
  fetchQuoteRules,
  getTaskSpace,
  getTaskSpaceVersion,
  type QuoteRule,
} from "@/api/designApi";
import { HomeDesignEditor } from "@/lib/homeDesignEditor";
import type {
  HomeObject,
  HomeSurface,
  HomeVersionList,
} from "@/types/homeDesign";
import "./homeDesign.css";
import HomeDeliveryPanel from "./HomeDeliveryPanel";
import HomeAgentPanel from "./HomeAgentPanel";
import HomeAssetLibraryPanel from "./HomeAssetLibraryPanel";
import HomeSpaceImpactPanel from "./HomeSpaceImpactPanel";
import HomeObjectRequirements from "./HomeObjectRequirements";
import HomePointsPanel from "./HomePointsPanel";
import { objectRequirements } from "./homeDesignFields";
import { HomeAssetLibrary } from "@/lib/homeAssetLibrary";
import { HomeAssetCache, objectFromAsset } from "@/lib/homeAssets";
import { useHomeAssets } from "@/lib/useHomeAssets";
import {
  isSurfaceAreaQuoteRule,
  surfaceQuoteRuleId,
  surfaceQuoteRuleFallbackLabel,
  surfaceQuoteRuleLabel,
} from "@/lib/homeSurfacePricing";
const HomeDesignCanvas = lazy(() => import("./HomeDesignCanvas"));
const categories: Record<HomeObject["category"], string> = {
  furniture: "家具与收纳",
  equipment: "设备",
  lighting: "灯具",
  textile: "软装",
  fixture: "固定构件",
};
function Tool({
  label,
  children,
  onClick,
  disabled,
}: {
  label: string;
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
function NumberInput({
  label,
  name,
  value,
  min,
  max,
  readOnly,
}: {
  label: string;
  name: string;
  value: number;
  min?: number;
  max?: number;
  readOnly?: boolean;
}) {
  return (
    <label>
      {label}
      <input
        name={name}
        type="number"
        step="any"
        defaultValue={value}
        min={min}
        max={max}
        required
        readOnly={readOnly}
      />
    </label>
  );
}
export default function HomeDesignWorkspace({ taskId }: { taskId: number }) {
  const [surfaceKind, setSurfaceKind] = useState<HomeSurface["kind"]>("floor");
  const [surfaceWall, setSurfaceWall] = useState("");
  const editor = useMemo(
    () =>
      new HomeDesignEditor(
        taskId,
        {
          get: getHomeDesign,
          save: saveHomeDesign,
          space: getTaskSpace,
          spaceVersion: getTaskSpaceVersion,
          impact: previewHomeSpaceImpact,
        },
        window.localStorage,
      ),
    [taskId],
  );
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot);
  const assetCache=useMemo(()=>new HomeAssetCache(taskId,getHomeAsset),[taskId]);
  const library=useMemo(()=>new HomeAssetLibrary(taskId,{list:getHomeAssetOptions,freeze:freezeHomeAsset}),[taskId]);
  const agentLibrary=useMemo(()=>new HomeAssetLibrary(taskId,{list:getHomeAssetOptions,freeze:freezeHomeAsset}),[taskId]);
  const [mode, setMode] = useState<"2d" | "3d">("2d");
  const assets=useHomeAssets(assetCache,state.document?.objects ?? [],mode==="3d");
  const [showLibrary,setShowLibrary]=useState(false);
  const [roomId, setRoomId] = useState(""),
    [selected, setSelected] = useState<string | null>(null),
    [selectedPoint, setSelectedPoint] = useState<string | null>(null),
    [panel, setPanel] = useState<
      "objects" | "surfaces" | "points" | "history" | "delivery" | "agent" | "space-impact" | null
    >("objects"),
    [mobile, setMobile] = useState<"canvas" | "tools">("canvas"),
    [showCeiling, setShowCeiling] = useState(false),
    [versions, setVersions] = useState<HomeVersionList | null>(null),
    [error, setError] = useState(""),
    [quoteRules, setQuoteRules] = useState<QuoteRule[]>([]),
    [quoteRuleError, setQuoteRuleError] = useState(""),
    [quoteRulesLoading, setQuoteRulesLoading] = useState(true),
    [historyBusy, setHistoryBusy] = useState(false);
  useEffect(() => {
    void editor.load();
  }, [editor]);
  useEffect(() => {
    let active = true;
    setQuoteRules([]);
    setQuoteRuleError("");
    setQuoteRulesLoading(true);
    void fetchQuoteRules()
      .then((rules) => {
        if (!active) return;
        setQuoteRules(rules.filter(isSurfaceAreaQuoteRule));
        setQuoteRuleError("");
      })
      .catch(() => {
        if (active) setQuoteRuleError("计价规则暂时无法读取，可先保存材料并稍后补充报价");
      })
      .finally(() => {
        if (active) setQuoteRulesLoading(false);
      });
    return () => {
      active = false;
    };
  }, [taskId]);
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (state.dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [state.dirty]);
  const document = state.document,
    space = state.space;
  useEffect(() => {
    if (space && roomId && !space.rooms.some(r => r.id === roomId)) setRoomId("");
  }, [space, roomId]);
  const object = document?.objects.find((o) => o.id === selected);
  const room = space?.rooms.find((r) => r.id === roomId) ?? space?.rooms[0];
  const change = (next: NonNullable<typeof document>) => {
    try {
      editor.change(next);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "修改失败");
    }
  };
  const select = (id: string) => {
    setSelectedPoint(null);
    setSelected(id);
    setPanel("objects");
    setMobile("tools");
  };
  const add = () => {
    if (!document || !room) return;
    const id = crypto.randomUUID();
    const o: HomeObject = {
      id,
      room_id: room.id,
      name: "新物件",
      category: "furniture",
      position: {
        x: room.polygon.reduce((a, p) => a + p.x, 0) / room.polygon.length,
        y: 0,
        z: room.polygon.reduce((a, p) => a + p.z, 0) / room.polygon.length,
      },
      size: { width: 1, height: 0.8, depth: 0.6 },
      rotation: 0,
      material: { name: "待选材料", color: "#c6d9d2" },
    };
    change({ ...document, objects: [...document.objects, o] });
    select(id);
  };
  const saveObject = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!document || !object) return;
    const f = new FormData(event.currentTarget),
      n = (k: string) => Number(f.get(k));
    let requirements: ReturnType<typeof objectRequirements>;
    try { requirements=objectRequirements(f,!!object.asset_id); } catch(e){setError(e instanceof Error?e.message:"安装参数无效");return;}
    change({
      ...document,
      objects: document.objects.map((o) =>
        o.id === object.id
          ? {
              ...o,
              ...requirements,
              name: String(f.get("name")),
              room_id: String(f.get("room")),
              category: o.asset_id ? o.category : f.get("category") as HomeObject["category"],
              position: { x: n("x"), y: n("y"), z: n("z") },
              size: o.asset_id ? o.size : {
                width: n("width"),
                height: n("height"),
                depth: n("depth"),
              },
              rotation: n("rotation"),
              material: o.asset_id ? o.material : {
                name: String(f.get("material")),
                color: String(f.get("color")),
              },
            }
          : o,
      ),
    });
  };
  const activeWall =
    space?.walls.find(
      (w) => w.id === surfaceWall && w.room_ids.includes(room?.id ?? ""),
    )?.id ??
    space?.walls.find((w) => w.room_ids.includes(room?.id ?? ""))?.id ??
    "";
  const activeSurface = document?.surfaces.find(
    (s) =>
      s.room_id === room?.id &&
      s.kind === surfaceKind &&
      s.wall_id === (surfaceKind === "wall" ? activeWall : null),
  );
  const saveSurface = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!document || !room) return;
    const f = new FormData(event.currentTarget);
    const kind = f.get("kind") as HomeSurface["kind"],
      wall = kind === "wall" ? String(f.get("wall")) : null,
      quoteRuleId = surfaceQuoteRuleId(f.get("quote_rule"));
    const existing = document.surfaces.find(
      (s) => s.room_id === room.id && s.kind === kind && s.wall_id === wall,
    );
    const next: HomeSurface = {
      id: existing?.id ?? crypto.randomUUID(),
      room_id: room.id,
      kind,
      wall_id: wall,
      ...(quoteRuleId ? { quote_rule_id: quoteRuleId } : {}),
      material: {
        name: String(f.get("material")),
        color: String(f.get("color")),
      },
    };
    change({
      ...document,
      surfaces: [...document.surfaces.filter((s) => s.id !== next.id), next],
    });
  };
  const history = async (more = false) => {
    setPanel("history");
    setMobile("tools");
    setHistoryBusy(true);
    try {
      const r = await getHomeDesignVersions(
        taskId,
        more ? (versions?.next_before_version ?? undefined) : undefined,
      );
      setVersions(
        more && versions
          ? { ...r, versions: [...versions.versions, ...r.versions] }
          : r,
      );
      setError("");
    } catch {
      setError("历史读取失败，请重试");
    } finally {
      setHistoryBusy(false);
    }
  };
  const restore = async (v: number) => {
    if (state.dirty && !window.confirm("载入历史将替换本机修改，是否继续？"))
      return;
    setHistoryBusy(true);
    try {
      await editor.restore(await getHomeDesignVersion(taskId, v));
      setSelected(null);
      setRoomId("");
    } catch {
      setError("历史版本读取失败");
    } finally {
      setHistoryBusy(false);
    }
  };
  const download = () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            { task_id: taskId, base_version: state.version, document },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const link = window.document.createElement("a");
    link.href = url;
    link.download = `家装草稿-${taskId}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <main className="hd-workspace">
      <header className="hd-header">
        <Link aria-label="返回整屋户型" to={`/design/${taskId}/space`}>
          <ArrowLeft size={20} />
        </Link>
        <div>
          <h1>整屋家装设计</h1>
          <small>
            空间 V{document?.space_version ?? "—"} · 家装 V{state.version} ·{" "}
            {state.status === "load-error"
              ? "读取失败，显示上次内容"
              : state.status === "loading"
                ? "正在读取"
                : state.status === "conflict"
                  ? "版本冲突"
                  : state.dirty
                    ? "未保存修改"
                    : state.version === 0
                      ? "尚未保存"
                      : "已同步"}
          </small>
        </div>
        <div className="hd-actions">
          <Tool
            label="撤销"
            onClick={() => editor.undo()}
            disabled={!editor.editable || !state.canUndo}
          >
            <Undo2 />
          </Tool>
          <Tool
            label="重做"
            onClick={() => editor.redo()}
            disabled={!editor.editable || !state.canRedo}
          >
            <Redo2 />
          </Tool>
          <Tool label="下载草稿" onClick={download} disabled={!document}>
            <Download />
          </Tool>
          <Tool
            label="重新载入"
            disabled={state.status === "saving"}
            onClick={() => {
              if (
                !state.dirty ||
                window.confirm("重新载入会丢弃本机修改，是否继续？")
              )
                void editor.load(true);
            }}
          >
            <RefreshCw />
          </Tool>
          <button
            className="hd-save"
            disabled={
              (!state.dirty && state.version > 0) ||
              !["ready", "error"].includes(state.status)
            }
            onClick={() => void editor.save()}
          >
            <Save size={17} />
            {state.status === "error"
              ? "重试保存"
              : state.status === "saving"
                ? "保存中"
                : "保存草稿"}
          </button>
        </div>
      </header>
      {(state.message || state.storageWarning || error) && (
        <div className="hd-notice" role="status">
          {error || state.message} {state.storageWarning}
        </div>
      )}
      {state.status === "loading" ? (
        <div className="hd-empty">正在读取设计与绑定空间…</div>
      ) : !space || !document ? (
        <div className="hd-empty">
          <h2>
            {state.status === "blocked" ? "先确认您的户型" : "设计暂时无法读取"}
          </h2>
          <p>{state.message}</p>
          <Link to={`/design/${taskId}/space`}>返回整屋户型</Link>
          <button onClick={() => void editor.load()}>重试读取</button>
        </div>
      ) : (
        <>
          <nav className="hd-toolbar">
            <select
              aria-label="查看房间"
              value={roomId}
              onChange={(e) => {
                setRoomId(e.target.value);
                setSelected(null);
              }}
            >
              <option value="">整屋</option>
              {space.rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <div className="hd-segment">
              <button
                aria-pressed={mode === "2d"}
                onClick={() => setMode("2d")}
              >
                <Map size={16} />
                2D
              </button>
              <button
                aria-pressed={mode === "3d"}
                onClick={() => setMode("3d")}
              >
                <Box size={16} />
                3D
              </button>
            </div>
            <button
              aria-pressed={panel === "objects"}
              onClick={() => {
                setPanel(panel === "objects" ? null : "objects");
                setMobile("tools");
              }}
            >
              <Layers size={16} />
              物件
            </button>
            <button
              aria-pressed={panel === "surfaces"}
              onClick={() => {
                setPanel(panel === "surfaces" ? null : "surfaces");
                setMobile("tools");
              }}
            >
              <SlidersHorizontal size={16} />
              表面材料
            </button>
            <Tool label="版本历史" onClick={() => void history()}>
              <History />
            </Tool>
            <button aria-pressed={panel === "points"} onClick={()=>{setPanel("points");setMobile("tools");}}><MapPin size={16}/>已有点位</button>
            <button aria-pressed={panel === "space-impact"} onClick={() => {setPanel("space-impact");setMobile("tools");}}><RefreshCw size={16}/>更新户型</button>
            <button
              onClick={() => {
                setPanel("agent");
                setMobile("tools");
              }}
              aria-pressed={panel === "agent"}
            >
              AI 建议
            </button>
            <button
              aria-pressed={panel === "delivery"}
              onClick={() => {
                setPanel("delivery");
                setMobile("tools");
              }}
            >
              <Download size={16} />
              清单与比较
            </button>
            {mode === "3d" && (
              <label className="hd-toggle">
                <input
                  type="checkbox"
                  checked={showCeiling}
                  onChange={(e) => setShowCeiling(e.target.checked)}
                />
                顶面
              </label>
            )}
          </nav>
          <div className="hd-mobile-tabs">
            <button
              aria-pressed={mobile === "canvas"}
              onClick={() => setMobile("canvas")}
            >
              当前方案
            </button>
            <button
              aria-pressed={mobile === "tools"}
              onClick={() => {
                setMobile("tools");
                setPanel(panel ?? "objects");
              }}
            >
              编辑与清单
            </button>
          </div>
          <div className={`hd-body ${panel ? "has-panel" : ""}`}>
            <section
              className={`hd-canvas ${mobile === "tools" ? "mobile-hidden" : ""}`}
            >
              <Suspense fallback={<div className="hd-empty">加载画布…</div>}>
                <HomeDesignCanvas
                  space={space}
                  document={document}
                  roomId={roomId}
                  mode={mode}
                  selected={selected}
                  selectedPoint={selectedPoint}
                  onSelectPoint={id=>{setSelectedPoint(id);setSelected(null);setPanel("points");setMobile("tools");}}
                  onSelect={select}
                  showCeiling={showCeiling}
                  assets={assets.entries}
                  onAssetError={assets.renderError}
                />
              </Suspense>
              <div className="hd-caption">
                {document.objects.some(o=>o.asset_id) ? "冻结家具与概念物件 · 未包含安装与工程审核" : "概念体块 · 非精细家具模型 · 未包含安装与工程审核"}
              </div>
            </section>
            {panel && (
              <aside
                className={`hd-panel ${mobile === "canvas" ? "mobile-hidden" : ""}`}
              >
                <div className="hd-panel-title">
                  <h2>
                    {panel === "objects"
                      ? "物件与属性"
                      : panel === "surfaces"
                        ? "房间表面"
                        : panel === "agent"
                          ? "AI 设计建议"
                          : panel === "delivery"
                            ? "清单与比较"
                            : panel === "space-impact" ? "户型更新影响" : panel === "points" ? "已有点位" : "版本历史"}
                  </h2>
                  <Tool
                    label="收起工具"
                    onClick={() => {
                      setPanel(null);
                      setMobile("canvas");
                    }}
                  >
                    <X />
                  </Tool>
                </div>
                {panel === "objects" && (
                  <>
                    <button className="hd-add" aria-expanded={showLibrary} onClick={()=>setShowLibrary(!showLibrary)}>家具库</button>
                    {showLibrary && room && <HomeAssetLibraryPanel library={library} disabled={!editor.editable} roomName={room.name} onAdd={asset=>{
                      const latest=editor.getSnapshot();
                      const currentRoom=latest.space?.rooms.find(r=>r.id===room.id);
                      if(!editor.editable || !latest.document || !currentRoom || asset.task_id!==taskId)return;
                      const item=objectFromAsset(asset,currentRoom);
                      change({...latest.document,objects:[...latest.document.objects,item]});
                      select(item.id);
                    }}/>}
                    {document.objects.some(o=>o.asset_id && assets.entries[o.asset_id]?.error) && <div role="alert"><p>部分家具模型读取失败，显示占位线框</p><button onClick={assets.retry}><RefreshCw size={16}/>重试模型</button></div>}
                    <button
                      className="hd-add"
                      onClick={add}
                      disabled={!editor.editable}
                    >
                      <Plus size={17} />
                      添加概念物件
                    </button>
                    <div className="hd-list">
                      {document.objects
                        .filter((o) => !roomId || o.room_id === roomId)
                        .map((o) => (
                          <button
                            key={o.id}
                            aria-pressed={selected === o.id}
                            onClick={() => select(o.id)}
                          >
                            <span
                              className="hd-swatch"
                              style={{ background: o.material.color }}
                            />
                            {o.name}
                            <small>{categories[o.category]}</small>
                          </button>
                        ))}
                      {!document.objects.length && <p>当前尚未添加物件</p>}
                    </div>
                    {object && (
                      <form key={JSON.stringify(object)} onSubmit={saveObject}>
                        <fieldset disabled={!editor.editable}>
                          {object.asset_id && <div className="hd-asset-source">{assets.entries[object.asset_id]?.asset ? <><strong>{assets.entries[object.asset_id].asset!.kind==="product"?"商品家具":"本任务作品"}</strong><p>冻结来源 V{assets.entries[object.asset_id].asset!.source_version} · 待报价</p></> : <p>{assets.entries[object.asset_id]?.error || "正在读取冻结来源…"}</p>}</div>}
                          <label>
                            名称
                            <input
                              name="name"
                              defaultValue={object.name}
                              maxLength={100}
                              required
                            />
                          </label>
                          <label>
                            类别
                            <select
                              name="category"
                              defaultValue={object.category}
                              disabled={!!object.asset_id}
                            >
                              {Object.entries(categories).map(
                                ([key, label]) => (
                                  <option key={key} value={key}>
                                    {label}
                                  </option>
                                ),
                              )}
                            </select>
                          </label>
                          <label>
                            所属房间
                            <select name="room" defaultValue={object.room_id}>
                              {space.rooms.map((r) => (
                                <option key={r.id} value={r.id}>
                                  {r.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <div className="hd-fields">
                            <NumberInput
                              label="宽（米）"
                              name="width"
                              value={object.size.width}
                              readOnly={!!object.asset_id}
                              min={0.001}
                              max={100}
                            />
                            <NumberInput
                              label="深（米）"
                              name="depth"
                              value={object.size.depth}
                              readOnly={!!object.asset_id}
                              min={0.001}
                              max={100}
                            />
                            <NumberInput
                              label="高（米）"
                              name="height"
                              value={object.size.height}
                              readOnly={!!object.asset_id}
                              min={0.001}
                              max={8}
                            />
                            <NumberInput
                              label="旋转（度）"
                              name="rotation"
                              value={object.rotation}
                              min={-360}
                              max={360}
                            />
                            <NumberInput
                              label="全局 X（米）"
                              name="x"
                              value={object.position.x}
                              min={-10000}
                              max={10000}
                            />
                            <NumberInput
                              label="全局 Z（米）"
                              name="z"
                              value={object.position.z}
                              min={-10000}
                              max={10000}
                            />
                            <NumberInput
                              label="离地（米）"
                              name="y"
                              value={object.position.y}
                              readOnly={!!object.asset_id}
                              min={0}
                              max={8}
                            />
                          </div>
                          <label>
                            材料名称
                            <input
                              name="material"
                              defaultValue={object.material.name}
                              readOnly={!!object.asset_id}
                              required
                              maxLength={100}
                            />
                          </label>
                          <label>
                            颜色
                            <input
                              name="color"
                              type="color"
                              defaultValue={object.material.color}
                              disabled={!!object.asset_id}
                            />
                          </label>
                          <HomeObjectRequirements object={object} space={space} points={document.points ?? []}/>
                          <button type="submit" className="hd-save">
                            应用修改
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              change({
                                ...document,
                                objects: document.objects.filter(
                                  (o) => o.id !== object.id,
                                ),
                              });
                              setSelected(null);
                            }}
                          >
                            <Trash2 size={16} />
                            删除物件
                          </button>
                        </fieldset>
                      </form>
                    )}
                  </>
                )}
                {panel === "surfaces" && room && (
                  <>
                    <label>
                      编辑房间
                      <select
                        value={room.id}
                        onChange={(e) => setRoomId(e.target.value)}
                      >
                        {space.rooms.map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <form
                      key={`${room.id}-${surfaceKind}-${activeWall}-${activeSurface?.quote_rule_id ?? "none"}-${JSON.stringify(activeSurface?.material)}`}
                      onSubmit={saveSurface}
                    >
                      <fieldset disabled={!editor.editable}>
                        <label>
                          表面
                          <select
                            name="kind"
                            value={surfaceKind}
                            onChange={(e) =>
                              setSurfaceKind(
                                e.target.value as HomeSurface["kind"],
                              )
                            }
                          >
                            <option value="floor">地面</option>
                            <option value="wall">墙面</option>
                            <option value="ceiling">顶面</option>
                          </select>
                        </label>
                        {surfaceKind === "wall" && (
                          <label>
                            墙体
                            <select
                              name="wall"
                              value={activeWall}
                              onChange={(e) => setSurfaceWall(e.target.value)}
                              required
                            >
                              {space.walls
                                .filter((w) => w.room_ids.includes(room.id))
                                .map((w) => (
                                  <option key={w.id} value={w.id}>
                                    {w.id.slice(0, 12)}
                                  </option>
                                ))}
                            </select>
                          </label>
                        )}
                        <label>
                          材料名称
                          <input
                            name="material"
                            required
                            maxLength={100}
                            placeholder="填写材料或待选材料"
                            defaultValue={activeSurface?.material.name ?? ""}
                          />
                        </label>
                        <label>
                          颜色
                          <input
                            name="color"
                            type="color"
                            defaultValue={
                              activeSurface?.material.color ?? "#dadfe4"
                            }
                          />
                        </label>
                        <label>
                          材料计价规则
                          <select
                            name="quote_rule"
                            defaultValue={activeSurface?.quote_rule_id ?? ""}
                          >
                            <option value="">不绑定（估价时列为待报价）</option>
                            {activeSurface?.quote_rule_id &&
                              !quoteRules.some(
                                (rule) => rule.id === activeSurface.quote_rule_id,
                              ) && (
                                <option value={activeSurface.quote_rule_id}>
                                  {surfaceQuoteRuleFallbackLabel(
                                    activeSurface.quote_rule_id,
                                    quoteRulesLoading
                                      ? "loading"
                                      : quoteRuleError
                                        ? "error"
                                        : "missing",
                                  )}
                                </option>
                              )}
                            {quoteRules.map((rule) => (
                              <option key={rule.id} value={rule.id}>
                                {surfaceQuoteRuleLabel(rule)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <p className="hd-field-note">
                          规则仅用于当前表面；损耗、最低量、安装与运输费按该表面独立计算。
                        </p>
                        {quoteRuleError && (
                          <p className="hd-field-warning" role="status">
                            {quoteRuleError}
                          </p>
                        )}
                        <button
                          className="hd-save"
                          type="submit"
                          disabled={surfaceKind === "wall" && !activeWall}
                        >
                          应用饰面
                        </button>
                      </fieldset>
                    </form>
                    <div className="hd-list">
                      {document.surfaces
                        .filter((s) => s.room_id === room.id)
                        .map((s) => (
                          <div key={s.id}>
                            <span
                              className="hd-swatch"
                              style={{ background: s.material.color }}
                            />
                            <button
                              onClick={() => {
                                setSurfaceKind(s.kind);
                                setSurfaceWall(s.wall_id ?? "");
                              }}
                            >
                              {
                                {
                                  floor: "地面",
                                  wall: "墙面",
                                  ceiling: "顶面",
                                }[s.kind]
                              }{" "}
                              · {s.material.name}
                              <small>
                                {s.quote_rule_id
                                  ? `计价规则 #${s.quote_rule_id}`
                                  : "待绑定报价"}
                              </small>
                            </button>
                            <Tool
                              label={`删除${s.material.name}饰面`}
                              disabled={!editor.editable}
                              onClick={() =>
                                change({
                                  ...document,
                                  surfaces: document.surfaces.filter(
                                    (x) => x.id !== s.id,
                                  ),
                                })
                              }
                            >
                              <Trash2 />
                            </Tool>
                          </div>
                        ))}
                    </div>
                  </>
                )}
                {panel === "space-impact" && <HomeSpaceImpactPanel editor={editor}/>}
                {panel === "points" && <HomePointsPanel document={document} space={space} disabled={!editor.editable} selected={selectedPoint} onSelect={id=>{setSelectedPoint(id);setSelected(null);}} onChange={next=>{editor.change(next);setError("");}}/>}
                {panel === "agent" && (
                  <HomeAgentPanel
                    taskId={taskId}
                    version={state.version}
                    document={document}
                    dirty={state.dirty}
                    editable={editor.editable}
                    assetLibrary={agentLibrary}
                    onApply={change}
                    onApplied={() => setMobile("canvas")}
                  />
                )}
                {panel === "delivery" && (
                  <HomeDeliveryPanel
                    key={`${taskId}-${state.version}`}
                    taskId={taskId}
                    version={state.version}
                    dirty={state.dirty}
                  />
                )}
                {panel === "history" && (
                  <>
                    <button
                      onClick={() => void history()}
                      disabled={historyBusy}
                    >
                      刷新历史
                    </button>
                    {versions?.versions.map((v) => (
                      <div className="hd-history" key={v.version}>
                        <strong>
                          V{v.version} · 空间 V{v.space_version}
                        </strong>
                        <small>
                          {v.object_count} 件物件 ·{" "}
                          {v.valid ? "几何检查通过" : "待修正"} ·{" "}
                          {new Date(v.created_at).toLocaleString()}
                        </small>
                        <button
                          disabled={!editor.editable || historyBusy}
                          onClick={() => void restore(v.version)}
                        >
                          载入为草稿
                        </button>
                      </div>
                    ))}
                    {versions?.next_before_version && (
                      <button
                        disabled={historyBusy}
                        onClick={() => void history(true)}
                      >
                        更多版本
                      </button>
                    )}
                  </>
                )}
              </aside>
            )}
          </div>
          <footer className="hd-validation">
            {state.validation ? (
              state.validation.valid ? (
                "当前几何检查通过；不代表可施工。"
              ) : (
                <>
                  <strong>待修正 · {state.validation.issues.length} 项</strong>
                  {state.validation.issues.map((i, n) => (
                    <p key={n}>{i.message}</p>
                  ))}
                </>
              )
            ) : (
              "修改后尚未检查，保存草稿时执行几何校验。"
            )}
          </footer>
        </>
      )}
    </main>
  );
}
