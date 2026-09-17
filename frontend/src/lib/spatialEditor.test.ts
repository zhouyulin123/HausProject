import { describe,expect,it,vi } from "vitest";
import { SpatialEditor } from "./spatialEditor";
import { emptySpatialDocument,rectangleRoom,scaleSpatialDocument,removeSpatialRoom,buildRoomWalls,spatialBounds,validateSpatialDraft,updateSpatialRoom } from "./spatialGeometry";
import type { SpatialDocument } from "@/types/spatial";
const document=(): SpatialDocument => ({ ...emptySpatialDocument(),rooms: [rectangleRoom("r1","客厅",0,0,4,3,2.8)] });
const store=() => { const data=new Map<string,string>(); return { getItem: (k: string) => data.get(k)??null,setItem: (k: string,v: string) => { data.set(k,v); },removeItem: (k: string) => { data.delete(k); } }; };
describe("整屋编辑操作",() => {
  it("修改房间不改写独立墙高，降低层高不能截断墙体",() => {
    const doc=buildRoomWalls(document(),"r1",.12);
    doc.walls[0].height=1.2;
    const updated=updateSpatialRoom(doc,{ ...doc.rooms[0],name: "新名称" });
    expect(updated.walls).toEqual(doc.walls);
    expect(() => updateSpatialRoom(doc,{ ...doc.rooms[0],height: 2.5 })).toThrow("墙体");
    expect(updateSpatialRoom(doc,{ ...doc.rooms[0],height: 3 }).walls).toEqual(doc.walls);
  });
  it("按同一原点缩放所有空间与开口，保留垂直尺寸",() => {
    const doc=buildRoomWalls(document(),"r1",0.12);
    doc.openings=[{ id: "o",wall_id: doc.walls[0].id,type: "door",offset: 1,width: 0.8,height: 2.1,sill_height: 0 }];
    const scaled=scaleSpatialDocument(doc,2);
    expect(scaled.rooms[0].polygon[1].x).toBe(8);
    expect(scaled.openings[0]).toMatchObject({ offset: 2,width: 1.6,height: 2.1 });
    expect(scaled.scale_status).toBe("unconfirmed");
    expect(doc.rooms[0].polygon[1].x).toBe(4);
  });
  it("校准同时缩放底图坐标框，不改变图片身份",() => {
    const doc=document();
    doc.source_image_id=8;
    Object.assign(doc,{ image_reference: { origin: { x: 1,z: 2 },width: 10,depth: 8 } });
    const scaled=scaleSpatialDocument(doc,2) as SpatialDocument&{
      image_reference: {
        origin: {
          x: number;
          z: number;
        };
        width: number;
        depth: number;
      };
    };
    expect(scaled.image_reference).toEqual({ origin: { x: 2,z: 4 },width: 20,depth: 16 });
    expect(scaled.source_image_id).toBe(8);
  });
  it("相邻房间共用墙体，删除房间不会丢失另一侧引用",() => {
    let doc=document();
    doc.rooms.push(rectangleRoom("r2","卧室",4,0,3,3,2.8));
    doc=buildRoomWalls(buildRoomWalls(doc,"r1",0.12),"r2",0.12);
    expect(doc.walls).toHaveLength(7);
    expect(doc.walls.filter(w => w.room_ids.length===2)).toHaveLength(1);
    const after=removeSpatialRoom(doc,"r1");
    expect(after.walls).toHaveLength(4);
    expect(after.walls.every(w => w.room_ids.join()==="r2")).toBe(true);
  });
  it("部分共边会切分墙段，并保留原有开口的世界位置",() => {
    let doc=buildRoomWalls(document(),"r1",0.12);
    doc.rooms.push(rectangleRoom("r2","卧室",4,1,3,2,2.8));
    doc=buildRoomWalls(doc,"r2",0.12);
    expect(doc.walls.filter(w => w.room_ids.length===2)).toHaveLength(1);
    expect(doc.walls).toHaveLength(8);
  });
  it("墙段切分后门的全局位置不变，跨分界的门不能被截断",() => {
    let doc=buildRoomWalls(document(),"r1",.12);
    const wall=doc.walls[1];
    doc.openings=[{ id: "o",wall_id: wall.id,type: "door",offset: 1.5,width: .8,height: 2.1,sill_height: 0 }];
    doc.rooms.push(rectangleRoom("r2","卧室",4,1,3,2,2.8));
    const next=buildRoomWalls(doc,"r2",.12);
    const bound=next.walls.find(w => w.id===next.openings[0].wall_id)!;
    expect(bound.start.z+next.openings[0].offset).toBeCloseTo(1.5);
    doc.openings[0].offset=.5;
    expect(() => buildRoomWalls(doc,"r2",.12)).toThrow("跨越");
  });
  it("不接受无效尺寸、缺失房间和不一致的共享墙厚",() => {
    expect(() => rectangleRoom("r","",0,0,4,3,2.8)).toThrow();
    expect(() => rectangleRoom("r","房间",0,0,-1,3,2.8)).toThrow();
    expect(() => scaleSpatialDocument(document(),0)).toThrow();
    expect(() => buildRoomWalls(document(),"r1",0)).toThrow();
    expect(() => buildRoomWalls(document(),"missing",.12)).toThrow();
    expect(() => buildRoomWalls(buildRoomWalls(document(),"r1",.12),"r1",.2)).toThrow("墙厚");
  });
  it("画布取景同时覆盖底图和全局房间坐标",() => {
    expect(spatialBounds(emptySpatialDocument()).width).toBe(10);
    const doc=document();
    doc.image_reference={ origin: { x: -2,z: -3 },width: 12,depth: 15 };
    doc.source_image_id=1;
    expect(spatialBounds(doc)).toEqual({ minX: -2,minZ: -3,width: 12,depth: 15 });
    expect(validateSpatialDraft(doc)).toBeNull();
  });
  it.each([
    (d: SpatialDocument) => { d.rooms[0].name=""; },
    (d: SpatialDocument) => { d.rooms[0].polygon[1]={ ...d.rooms[0].polygon[0] }; },
    (d: SpatialDocument) => { d.rooms[0].polygon[1].x=Infinity; },
    (d: SpatialDocument) => { d.rooms=Array(51).fill(d.rooms[0]); },
    (d: SpatialDocument) => { d.image_reference={ origin: { x: 0,z: 0 },width: 0,depth: 5 }; },
    (d: SpatialDocument) => { d.walls[0].room_ids=["missing"]; },
    (d: SpatialDocument) => { d.openings=[{ id: "o",wall_id: d.walls[0].id,type: "door",offset: 3.5,width: 1,height: 2,sill_height: 0 }]; },
  ])("无效草稿在渲染和保存前得到明确校验",mutate => {
    const doc=buildRoomWalls(document(),"r1",.12);
    mutate(doc);
    expect(validateSpatialDraft(doc)).toBeTypeOf("string");
  });
});
describe("整屋保存恢复",() => {
  it("网络失败保留幂等键，重试成功才清除草稿",async () => {
    const storage=store();
    const save=vi.fn().mockRejectedValueOnce(new Error("网络中断")).mockImplementation(async (_id,p) => ({ task_id: 42,version: 1,document: p.document }));
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 0,document: null }),save },storage);
    await editor.load();
    editor.change(document());
    await editor.save();
    expect(editor.snapshot.status).toBe("error");
    expect(editor.snapshot.dirty).toBe(true);
    await editor.save();
    expect(save.mock.calls[0][1]).toEqual(save.mock.calls[1][1]);
    expect(editor.snapshot.version).toBe(1);
    expect(editor.snapshot.dirty).toBe(false);
  });
  it("冲突保留草稿与基准版本，不能静默覆盖远端",async () => {
    const storage=store();
    const save=vi.fn().mockRejectedValue({ status: 409 });
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 1,document: document() }),save },storage);
    await editor.load();
    const changed=document();
    changed.rooms[0].name="书房";
    editor.change(changed);
    await editor.save();
    expect(editor.snapshot.status).toBe("conflict");
    expect(editor.snapshot.document?.rooms[0].name).toBe("书房");
    const restored=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 2,document: document() }),save },storage);
    await restored.load();
    expect(restored.snapshot.status).toBe("conflict");
    expect(restored.snapshot.version).toBe(1);
  });
  it("读取失败不能建立空空间覆盖远端",async () => {
    const save=vi.fn();
    const editor=new SpatialEditor(42,{ get: async () => { throw Error("离线"); },save },store());
    await editor.load();
    editor.change(document());
    await editor.save();
    expect(save).not.toHaveBeenCalled();
    expect(editor.snapshot.status).toBe("load-error");
  });
  it("撤销与重做不会改变服务端版本",async () => {
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 1,document: document() }),save: vi.fn() },store());
    await editor.load();
    const next=document();
    next.rooms[0].name="卧室";
    editor.change(next);
    editor.undo();
    expect(editor.snapshot.dirty).toBe(false);
    editor.redo();
    expect(editor.snapshot.dirty).toBe(true);
    expect(editor.snapshot.version).toBe(1);
  });
  it("校验拒绝后可修正并使用新的幂等键",async () => {
    const save=vi.fn().mockRejectedValueOnce({ status: 422,detail: [{ msg: "房间重叠" }] }).mockImplementation(async (_id,p) => ({ task_id: 42,version: 1,document: p.document }));
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 0,document: null }),save },store());
    await editor.load();
    editor.change(document());
    await editor.save();
    expect(editor.snapshot.message).toBe("房间重叠");
    expect(editor.editable).toBe(true);
    const changed=document();
    changed.rooms[0].name="修正";
    editor.change(changed);
    await editor.save();
    expect(save.mock.calls[0][1].client_mutation_id).not.toBe(save.mock.calls[1][1].client_mutation_id);
  });
  it("保存中的重复点击和修改不能覆盖请求快照",async () => {
    let resolve!: (response: unknown) => void;
    const save=vi.fn(() => new Promise<any>(r => { resolve=r; }));
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 0,document: null }),save },store());
    await editor.load();
    editor.change(document());
    const pending=editor.save();
    await editor.save();
    const changed=document();
    changed.rooms[0].name="不能写入";
    editor.change(changed);
    expect(save).toHaveBeenCalledTimes(1);
    expect(editor.snapshot.document.rooms[0].name).toBe("客厅");
    resolve({ task_id: 42,version: 1,document: document() });
    await pending;
  });
  it("服务端已成功但确认丢失时，刷新能认领该版本",async () => {
    const storage=store();
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 0,document: null }),save: async () => { throw Error("响应中断"); } },storage);
    await editor.load();
    editor.change(document());
    await editor.save();
    const restored=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 1,document: document() }),save: vi.fn() },storage);
    await restored.load();
    expect(restored.snapshot.dirty).toBe(false);
    expect(restored.snapshot.version).toBe(1);
    expect(storage.getItem("haus-space-draft-v1-42")).toBeNull();
  });
  it("破损缓存不会阻断服务端恢复，存储配额失败会提示",async () => {
    const storage=store();
    storage.setItem("haus-space-draft-v1-42","{");
    const editor=new SpatialEditor(42,{ get: async () => ({ task_id: 42,version: 1,document: document() }),save: vi.fn() },storage);
    await editor.load();
    expect(editor.snapshot.storageWarning).toContain("无法读取");
    storage.setItem=() => { throw Error("quota"); };
    const next=document();
    next.rooms[0].name="草稿";
    editor.change(next);
    expect(editor.snapshot.storageWarning).toContain("未能保存");
  });
  it("迟到读取不能替换新一轮读取",async () => {
    let resolve!: (response: any) => void;
    const get=vi.fn().mockImplementationOnce(() => new Promise(r => { resolve=r; })).mockResolvedValue({ task_id: 42,version: 2,document: document() });
    const editor=new SpatialEditor(42,{ get,save: vi.fn() },store());
    const first=editor.load();
    await editor.load();
    resolve({ task_id: 42,version: 1,document: document() });
    await first;
    expect(editor.snapshot.version).toBe(2);
  });
  it("正常读取后恢复本机修改，显式重新载入才丢弃",async () => {
    const storage=store();
    const api={ get: async () => ({ task_id: 42,version: 1,document: document() }),save: vi.fn() };
    const editor=new SpatialEditor(42,api,storage);
    await editor.load();
    const changed=document();
    changed.rooms[0].name="书房";
    editor.change(changed);
    const restored=new SpatialEditor(42,api,storage);
    await restored.load();
    expect(restored.snapshot.document.rooms[0].name).toBe("书房");
    expect(restored.editable).toBe(true);
    await restored.load(true);
    expect(restored.snapshot.document.rooms[0].name).toBe("客厅");
    expect(restored.snapshot.dirty).toBe(false);
  });
});
