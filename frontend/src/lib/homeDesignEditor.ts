import type {
  HomeDesignDocument,
  HomeDesignResponse,
  HomeSaveRequest,
  HomeValidation,
  HomeSpaceImpact,
  HomeSpaceImpactRequest,
} from "@/types/homeDesign";
import type { SpatialResponse, SpatialDocument } from "@/types/spatial";
type API = {
  get: (id: number) => Promise<HomeDesignResponse>;
  save: (id: number, p: HomeSaveRequest) => Promise<HomeDesignResponse>;
  space: (id: number) => Promise<SpatialResponse>;
  spaceVersion: (id: number, v: number) => Promise<SpatialResponse>;
  impact?: (id: number, request: HomeSpaceImpactRequest) => Promise<HomeSpaceImpact>;
};
type Status =
  | "loading"
  | "load-error"
  | "ready"
  | "saving"
  | "error"
  | "conflict"
  | "blocked";
interface Snapshot {
  document: HomeDesignDocument | null;
  space: SpatialDocument | null;
  version: number;
  dirty: boolean;
  status: Status;
  message: string;
  validation: HomeValidation | null;
  canUndo: boolean;
  canRedo: boolean;
  storageWarning: string;
  impact: HomeSpaceImpact | null;
  impactBusy: boolean;
  impactError: string;
}
const encode = JSON.stringify;
function errorMessage(e: unknown) {
  const detail = (e as { detail?: { message?: string } | string })?.detail;
  return typeof detail === "string"
    ? detail
    : (detail?.message ??
        (e instanceof Error ? e.message : "请求失败，请重试"));
}
export function validHomeDraft(d: HomeDesignDocument): boolean {
  return (
    !!d &&
    d.schema_version === "home-design/1.0" &&
    Number.isInteger(d.space_version) &&
    d.space_version > 0 &&
    Array.isArray(d.objects) &&
    Array.isArray(d.surfaces) &&
    d.objects.length <= 500 &&
    d.surfaces.length <= 500 &&
    (d.points === undefined || (Array.isArray(d.points) && d.points.length <= 200 && new Set(d.points.map(p => p?.id)).size === d.points.length && d.points.every(p => p && typeof p.id === "string" && !!p.id.trim() && typeof p.name === "string" && !!p.name.trim() && typeof p.room_id === "string" && !!p.room_id && ["socket","switch","water","drain","network","other"].includes(p.kind) && typeof p.confirmed === "boolean" && [p.position?.x,p.position?.y,p.position?.z].every(Number.isFinite) && p.position.y >= 0 && p.position.y <= 8))) &&
    d.objects.every(
      (o) =>
        o &&
        typeof o.id === "string" &&
        (o.installation == null || (["floor","wall","ceiling"].includes(o.installation.kind) && (o.installation.kind === "wall" ? typeof o.installation.wall_id === "string" && !!o.installation.wall_id : o.installation.wall_id == null) && (!o.asset_id || o.installation.kind === "floor"))) &&
        (o.clearance == null || (typeof o.clearance.confirmed === "boolean" && [o.clearance.front,o.clearance.back,o.clearance.left,o.clearance.right,o.clearance.above].every(n => Number.isFinite(n) && n >= 0 && n <= 10))) &&
        (o.point_requirement == null || (typeof o.point_requirement.point_id === "string" && !!o.point_requirement.point_id && Number.isFinite(o.point_requirement.max_distance_m) && o.point_requirement.max_distance_m >= 0 && o.point_requirement.max_distance_m <= 100)) &&
        (o.asset_id == null || (Number.isSafeInteger(o.asset_id) && o.asset_id > 0)) &&
        o.name?.trim() &&
        ["furniture", "equipment", "lighting", "textile", "fixture"].includes(
          o.category,
        ) &&
        [
          o.position?.x,
          o.position?.y,
          o.position?.z,
          o.size?.width,
          o.size?.height,
          o.size?.depth,
          o.rotation,
        ].every(Number.isFinite) &&
        o.size.width > 0 &&
        o.size.height > 0 &&
        o.size.depth > 0 &&
        /^#[0-9a-f]{6}$/i.test(o.material?.color),
    ) &&
    d.surfaces.every(
      (s) =>
        s &&
        typeof s.id === "string" &&
        ["floor", "wall", "ceiling"].includes(s.kind) &&
        /^#[0-9a-f]{6}$/i.test(s.material?.color),
    )
  );
}
export class HomeDesignEditor {
  private state: Snapshot = {
    document: null,
    space: null,
    version: 0,
    dirty: false,
    status: "loading",
    message: "",
    validation: null,
    canUndo: false,
    canRedo: false,
    storageWarning: "",
    impact: null,
    impactBusy: false,
    impactError: "",
  };
  private listeners = new Set<() => void>();
  private past: { document: HomeDesignDocument; space: SpatialDocument }[] = [];
  private future: { document: HomeDesignDocument; space: SpatialDocument }[] = [];
  private impactGeneration = 0;
  private impactBase = "";
  private saved = "";
  private pending: HomeSaveRequest | null = null;
  private generation = 0;
  constructor(
    private id: number,
    private api: API,
    private storage: Pick<Storage, "getItem" | "setItem" | "removeItem"> | null,
  ) {}
  private get key() {
    return `haus-home-design-draft-v1-${this.id}`;
  }
  subscribe = (f: () => void) => {
    this.listeners.add(f);
    return () => {
      this.listeners.delete(f);
    };
  };
  getSnapshot = () => this.state;
  get editable() {
    return this.state.status === "ready";
  }
  private publish(p: Partial<Snapshot>) {
    if ((p.document && encode(p.document) !== encode(this.state.document)) || (p.status && p.status !== "ready")) {
      this.impactGeneration++;
      p = { ...p, impact: null, impactBusy: false, impactError: "" };
    }
    this.state = {
      ...this.state,
      ...p,
      canUndo: !!this.past.length,
      canRedo: !!this.future.length,
    };
    this.listeners.forEach((f) => f());
  }
  private persist() {
    try {
      if (this.state.dirty || this.pending)
        this.storage?.setItem(
          this.key,
          encode({
            document: this.state.document,
            base_version: this.state.version,
            pending: this.pending,
          }),
        );
      else this.storage?.removeItem(this.key);
    } catch {
      this.publish({ storageWarning: "本机草稿保存失败，请下载备份。" });
    }
  }
  async load(discard = false) {
    if (this.state.status === "saving") return;
    const generation = ++this.generation;
    this.publish({ status: "loading", message: "" });
    try {
      const server = await this.api.get(this.id);
      if (generation !== this.generation) return;
      let draft: {
        document: HomeDesignDocument;
        base_version: number;
        pending: HomeSaveRequest | null;
      } | null = null;
      if (!discard)
        try {
          draft = JSON.parse(this.storage?.getItem(this.key) ?? "null");
          if (
            draft &&
            (!validHomeDraft(draft.document) ||
              !Number.isInteger(draft.base_version) ||
              draft.base_version < 0)
          )
            throw Error();
        } catch {
          draft = null;
          this.publish({ storageWarning: "本机草稿无效，未自动恢复。" });
        }
      if (
        draft?.pending &&
        (draft.pending.base_version !== draft.base_version ||
          encode(draft.pending.document) !== encode(draft.document) ||
          typeof draft.pending.client_mutation_id !== "string" ||
          !draft.pending.client_mutation_id.trim())
      )
        throw Error("本机待重试请求无效，请下载草稿后重新载入");
      const document = draft?.document ?? server.document;
      const response = document
        ? await this.api.spaceVersion(this.id, document.space_version)
        : await this.api.space(this.id);
      if (generation !== this.generation) return;
      if (document && response.version !== document.space_version)
        throw Error("空间版本不匹配，未载入替代空间");
      if (
        !response.document ||
        response.document.scale_status !== "confirmed" ||
        !response.document.rooms.length
      ) {
        this.publish({
          status: "blocked",
          message: "请先保存并确认整屋户型尺度。",
        });
        return;
      }
      const next = document ?? {
        schema_version: "home-design/1.0" as const,
        space_version: response.version,
        surfaces: [],
        objects: [],
      };
      this.saved = encode(server.document ?? next);
      this.past = [];
      this.future = [];
      const dirty = encode(next) !== this.saved;
      this.pending = dirty || server.version===0 ? (draft?.pending ?? null) : null;
      this.publish({
        document: next,
        space: response.document,
        version: dirty ? draft!.base_version : server.version,
        dirty,
        status:
          dirty && draft!.base_version !== server.version
            ? "conflict"
            : this.pending
              ? "error"
              : "ready",
        message: dirty
          ? "已保留本机草稿；如有版本冲突，请下载后重新载入。"
          : "",
        validation: dirty ? null : (server.validation ?? null),
      });
      this.persist();
    } catch (e) {
      if (generation === this.generation)
        this.publish({ status: "load-error", message: errorMessage(e) });
    }
  }
  change(document: HomeDesignDocument) {
    if (!this.editable) return;
    if (!validHomeDraft(document)) throw Error("尺寸、颜色或参数格式无效");
    if (document.space_version !== this.state.document?.space_version)
      throw Error("不能直接更换绑定空间版本");
    if (encode(document) === encode(this.state.document)) return;
    this.past = [...this.past.slice(-49), this.currentFrame()];
    this.future = [];
    this.pending = null;
    this.publish({
      document: structuredClone(document),
      dirty: encode(document) !== this.saved,
      validation: null,
      message: "",
    });
    this.persist();
  }
  undo() {
    if (!this.editable || !this.past.length) return;
    this.future.push(this.currentFrame());
    const { document, space } = this.past.pop()!;
    this.publish({
      document,
      space,
      dirty: encode(document) !== this.saved,
      validation: null,
    });
    this.persist();
  }
  redo() {
    if (!this.editable || !this.future.length) return;
    this.past.push(this.currentFrame());
    const { document, space } = this.future.pop()!;
    this.publish({
      document,
      space,
      dirty: encode(document) !== this.saved,
      validation: null,
    });
    this.persist();
  }
  private currentFrame() {
    return { document: this.state.document!, space: this.state.space! };
  }
  async previewSpaceImpact(document?: HomeDesignDocument, targetVersion?: number) {
    if (!this.editable || !this.state.document || !this.api.impact) return;
    const generation = ++this.impactGeneration;
    const base = encode(this.state.document);
    const candidate = structuredClone(document ?? this.state.document);
    this.publish({ impactBusy: true, impactError: "" });
    try {
      const target = targetVersion ?? (await this.api.space(this.id)).version;
      if (generation !== this.impactGeneration || !this.editable) return;
      const response = await this.api.impact(this.id, { document: candidate, target_space_version: target });
      if (generation !== this.impactGeneration || !this.editable || base !== encode(this.state.document)) return;
      if (response.task_id !== this.id || response.source_space_version !== candidate.space_version || response.target_space_version !== target || response.candidate_document.space_version !== target || response.target_space.scale_status !== "confirmed" || !response.target_space.rooms.length)
        throw Error("户型影响响应版本不匹配，未载入");
      this.impactBase = base;
      this.publish({ impact: response, impactBusy: false });
    } catch (e) {
      if (generation === this.impactGeneration) this.publish({ impactBusy: false, impactError: errorMessage(e) });
    }
  }
  async resolveSpaceReference(type: "object" | "surface" | "point", id: string, action: { roomId: string; wallId?: string } | "delete") {
    const impact = this.state.impact;
    if (!this.editable || !impact || this.impactBase !== encode(this.state.document)) return;
    const candidate = structuredClone(impact.candidate_document);
    candidate.space_version = this.state.document!.space_version;
    if (action !== "delete") {
      if (!impact.target_space.rooms.some(r => r.id === action.roomId)) throw Error("请选择目标房间");
      const surface = candidate.surfaces.find(s => s.id === id);
      const object = candidate.objects.find(o => o.id === id);
      const wallRequired = (type === "surface" && surface?.kind === "wall") || (type === "object" && object?.installation?.kind === "wall");
      if (wallRequired && !impact.target_space.walls.some(w => w.id === action.wallId && w.room_ids.includes(action.roomId))) throw Error("请选择所属房间的墙体");
    }
    if (type === "point") candidate.points = action === "delete" ? (candidate.points ?? []).filter(p=>p.id!==id) : (candidate.points ?? []).map(p=>p.id===id?{...p,room_id:action.roomId}:p);
    else if (type === "object") candidate.objects = action === "delete" ? candidate.objects.filter(o => o.id !== id) : candidate.objects.map(o => o.id === id ? {...o, room_id: action.roomId,...(o.installation?.kind === "wall" ? {installation:{...o.installation,wall_id:action.wallId!}}:{})} : o);
    else candidate.surfaces = action === "delete" ? candidate.surfaces.filter(s => s.id !== id) : candidate.surfaces.map(s => s.id === id ? {...s, room_id: action.roomId, wall_id: s.kind === "wall" ? action.wallId! : null} : s);
    await this.previewSpaceImpact(candidate, impact.target_space_version);
  }
  async resolveSpacePoint(objectId: string, pointId: string | null) {
    const impact = this.state.impact;
    if (!this.editable || !impact || this.impactBase !== encode(this.state.document)) return;
    const candidate = structuredClone(impact.candidate_document);
    const object = candidate.objects.find(item => item.id === objectId);
    if (!object?.point_requirement) throw Error("物件没有点位关联");
    if (pointId !== null && !candidate.points?.some(point => point.id === pointId && point.room_id === object.room_id)) throw Error("请选择物件所在房间的点位");
    object.point_requirement = pointId === null ? null : {...object.point_requirement, point_id: pointId};
    candidate.space_version = this.state.document!.space_version;
    await this.previewSpaceImpact(candidate, impact.target_space_version);
  }
  applySpaceImpact() {
    const impact = this.state.impact;
    if (!this.editable || !impact?.can_apply || impact.reference_issues.length || this.state.impactBusy || this.state.impactError || this.impactBase !== encode(this.state.document)) return;
    if (!validHomeDraft(impact.candidate_document)) throw Error("候选草稿无效");
    this.past = [...this.past.slice(-49), this.currentFrame()];
    this.future = [];
    this.publish({ document: structuredClone(impact.candidate_document), space: structuredClone(impact.target_space), dirty: encode(impact.candidate_document) !== this.saved, validation: impact.validation, message: "新户型已载入草稿，保存后形成新方案版本。", impact: null });
    this.persist();
  }
  async restore(response: HomeDesignResponse) {
    if (!this.editable || !response.document) return;
    const generation = ++this.generation;
    this.publish({ status: "loading" });
    try {
      const space = await this.api.spaceVersion(
        this.id,
        response.document.space_version,
      );
      if (generation !== this.generation) return;
      if (
        !space.document ||
        space.version !== response.document.space_version ||
        space.document.scale_status !== "confirmed"
      )
        throw Error("历史绑定空间不存在或尺度未确认");
      this.past = [];
      this.future = [];
      this.pending = null;
      this.publish({
        document: response.document,
        space: space.document,
        status: "ready",
        dirty: encode(response.document) !== this.saved,
        validation: null,
        message: "历史版本已载入草稿，保存后形成新版本。",
      });
      this.persist();
    } catch (e) {
      if (generation === this.generation)
        this.publish({ status: "ready", message: errorMessage(e) });
    }
  }
  async save() {
    if (
      (!this.state.dirty && this.state.version > 0) ||
      !this.state.document ||
      !["ready", "error"].includes(this.state.status)
    )
      return;
    const generation = ++this.generation;
    this.pending ??= {
      base_version: this.state.version,
      client_mutation_id: crypto.randomUUID(),
      document: structuredClone(this.state.document),
    };
    this.persist();
    this.publish({ status: "saving", message: "" });
    try {
      const r = await this.api.save(this.id, this.pending);
      if (generation !== this.generation) return;
      if (!r.document) throw Error("保存响应缺少文档");
      this.saved = encode(r.document);
      this.pending = null;
      this.publish({
        document: r.document,
        version: r.version,
        dirty: false,
        status: "ready",
        validation: r.validation ?? null,
        message:
          r.validation?.valid === false
            ? "已保存草稿，仍有待修正问题"
            : "已保存",
      });
      this.persist();
    } catch (e) {
      if (generation !== this.generation) return;
      const code = (e as { status?: number })?.status;
      if (code === 422) this.pending = null;
      this.publish({
        status: code === 409 ? "conflict" : code === 422 ? "ready" : "error",
        message:
          code === 409
            ? "版本冲突，本机修改已保留；下载备份后可重新载入。"
            : errorMessage(e),
      });
      this.persist();
    }
  }
}
