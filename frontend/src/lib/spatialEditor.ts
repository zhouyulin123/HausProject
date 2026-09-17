import type { SpatialDocument,SpatialResponse,SpatialSaveRequest } from "@/types/spatial";
import { emptySpatialDocument,spatialId,validateSpatialDraft } from "./spatialGeometry";
type Status="loading"|"load-error"|"ready"|"saving"|"error"|"invalid"|"conflict";
type StorageLike=Pick<Storage,"getItem"|"setItem"|"removeItem">;
type API={
  get: (id: number) => Promise<SpatialResponse>;
  save: (id: number,payload: SpatialSaveRequest) => Promise<SpatialResponse>;
};
export interface SpatialEditorSnapshot {
  document: SpatialDocument;
  version: number;
  status: Status;
  message: string;
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  storageWarning: string;
}
function message(error: unknown): string {
  const detail=(error as {
    detail?: unknown;
  })?.detail;
  if(typeof detail==="string")
    return detail;
  if(Array.isArray(detail))
    return detail.map(d => d.msg).filter(Boolean).join("；");
  if(detail&&typeof detail==="object"&&"message" in detail)
    return String(detail.message);
  return error instanceof Error? error.message:"空间保存失败";
}
export class SpatialEditor {
  snapshot: SpatialEditorSnapshot={ document: emptySpatialDocument(),version: 0,status: "loading",message: "",dirty: false,canUndo: false,canRedo: false,storageWarning: "" };
  private listeners=new Set<() => void>();
  private past: SpatialDocument[]=[];
  private future: SpatialDocument[]=[];
  private saved=JSON.stringify(emptySpatialDocument());
  private pending: SpatialSaveRequest|null=null;
  private generation=0;
  private key: string;
  constructor(private taskId: number,private api: API,private storage: StorageLike|null) { this.key=`haus-space-draft-v1-${taskId}`; }
  subscribe=(listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot=() => this.snapshot;
  private publish(patch: Partial<SpatialEditorSnapshot>) {
    this.snapshot={ ...this.snapshot,...patch,canUndo: !!this.past.length,canRedo: !!this.future.length };
    for(const listener of this.listeners)
      listener();
  }
  private persist() {
    try {
      if(this.snapshot.dirty)
        this.storage?.setItem(this.key,JSON.stringify({ base_version: this.snapshot.version,document: this.snapshot.document,pending: this.pending }));
      else
        this.storage?.removeItem(this.key);
    }
    catch {
      this.publish({ storageWarning: "本机草稿未能保存，请下载备份或保存到服务端。" });
    }
  }
  get editable() { return ["ready","invalid"].includes(this.snapshot.status); }
  async load(discard=false) {
    const generation=++this.generation;
    this.publish({ status: "loading",message: "" });
    try {
      const response=await this.api.get(this.taskId);
      if(generation!==this.generation)
        return;
      const server=response.document??emptySpatialDocument();
      this.saved=JSON.stringify(server);
      let draft: {
        base_version: number;
        document: SpatialDocument;
        pending: SpatialSaveRequest|null;
      }|null=null;
      try {
        if(!discard)
          draft=JSON.parse(this.storage?.getItem(this.key)??"null");
      }
      catch {
        this.publish({ storageWarning: "本机草稿无法读取，已读取服务端版本。" });
      }
      if(draft) {
        let valid=false;
        try {
          valid=Number.isInteger(draft.base_version)&&draft.base_version>=0&&!validateSpatialDraft(draft.document);
        }
        catch {
          valid=false;
        }
        if(!valid) {
          draft=null;
          this.publish({ storageWarning: "本机草稿格式无效，已读取服务端版本。" });
        }
      }
      this.past=[];
      this.future=[];
      this.pending=draft?.pending??null;
      if(draft&&JSON.stringify(draft.document)!==this.saved) {
        const conflict=draft.base_version!==response.version;
        this.publish({
          document: draft.document,version: draft.base_version,status: conflict? "conflict":this.pending? "error":"ready",dirty: true,
          message: conflict? "服务端已有新版本。本机草稿已保留，请下载草稿后重新载入。":this.pending? "上次保存结果未确认，请重试保存。":"已恢复本机未保存的修改"
        });
      }
      else {
        this.pending=null;
        this.publish({ document: server,version: response.version,status: "ready",dirty: false,message: "" });
      }
      this.persist();
    }
    catch(error) {
      if(generation===this.generation)
        this.publish({ status: "load-error",message: message(error) });
    }
  }
  change(document: SpatialDocument) {
    if(!this.editable)
      return;
    const error=validateSpatialDraft(document);
    if(error)
      throw Error(error);
    if(JSON.stringify(document)===JSON.stringify(this.snapshot.document))
      return;
    this.past=[...this.past.slice(-49),this.snapshot.document];
    this.future=[];
    this.pending=null;
    this.publish({ document: structuredClone(document),dirty: JSON.stringify(document)!==this.saved,status: "ready",message: "" });
    this.persist();
  }
  undo() {
    if(!this.editable||!this.past.length)
      return; this.future.unshift(this.snapshot.document); const document=this.past.pop()!; this.publish({ document,dirty: JSON.stringify(document)!==this.saved,status: "ready",message: "" }); this.persist();
  }
  redo() {
    if(!this.editable||!this.future.length)
      return; this.past.push(this.snapshot.document); const document=this.future.shift()!; this.publish({ document,dirty: JSON.stringify(document)!==this.saved,status: "ready",message: "" }); this.persist();
  }
  async save() {
    if(!this.snapshot.dirty||!["ready","invalid","error"].includes(this.snapshot.status))
      return;
    if(!this.snapshot.document.rooms.length) {
      this.publish({ status: "invalid",message: "至少需要一个房间" });
      return;
    }
    this.pending??={ base_version: this.snapshot.version,client_mutation_id: spatialId(),document: structuredClone(this.snapshot.document) };
    this.persist();
    this.publish({ status: "saving",message: "" });
    try {
      const response=await this.api.save(this.taskId,this.pending);
      this.saved=JSON.stringify(response.document);
      this.pending=null;
      this.publish({ version: response.version,document: response.document!,status: "ready",dirty: false,message: "已保存" });
      this.persist();
    }
    catch(error) {
      const status=(error as {
        status?: number;
      })?.status;
      if(status===422)
        this.pending=null;
      this.publish({ status: status===409? "conflict":status===422? "invalid":"error",message: status===409? "空间版本已变化，草稿已保留。请下载草稿或重新载入。":message(error) });
      this.persist();
    }
  }
}
