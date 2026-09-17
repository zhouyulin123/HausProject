import { describe, expect, it, vi } from "vitest";
import { SpatialEditor } from "./spatialEditor";
import { emptySpatialDocument, rectangleRoom, scaleSpatialDocument, removeSpatialRoom, buildRoomWalls } from "./spatialGeometry";
import type { SpatialDocument } from "@/types/spatial";

const document = (): SpatialDocument => ({ ...emptySpatialDocument(), rooms: [rectangleRoom("r1", "客厅", 0, 0, 4, 3, 2.8)] });
const store = () => { const data = new Map<string,string>(); return {getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>{data.set(k,v);},removeItem:(k:string)=>{data.delete(k);}}; };
describe("整屋编辑操作", () => {
  it("按同一原点缩放所有空间与开口，保留垂直尺寸", () => {
    const doc = buildRoomWalls(document(), "r1", 0.12);
    doc.openings = [{ id:"o", wall_id:doc.walls[0].id,type:"door",offset:1,width:0.8,height:2.1,sill_height:0 }];
    const scaled = scaleSpatialDocument(doc, 2);
    expect(scaled.rooms[0].polygon[1].x).toBe(8);
    expect(scaled.openings[0]).toMatchObject({offset:2,width:1.6,height:2.1});
    expect(scaled.scale_status).toBe("unconfirmed");
    expect(doc.rooms[0].polygon[1].x).toBe(4);
  });

  it("校准同时缩放底图坐标框，不改变图片身份",()=>{
    const doc=document();doc.source_image_id=8;
    Object.assign(doc,{image_reference:{origin:{x:1,z:2},width:10,depth:8}});
    const scaled=scaleSpatialDocument(doc,2) as SpatialDocument & {image_reference:{origin:{x:number;z:number};width:number;depth:number}};
    expect(scaled.image_reference).toEqual({origin:{x:2,z:4},width:20,depth:16});
    expect(scaled.source_image_id).toBe(8);
  });
  it("相邻房间共用墙体，删除房间不会丢失另一侧引用", () => {
    let doc=document(); doc.rooms.push(rectangleRoom("r2","卧室",4,0,3,3,2.8));
    doc=buildRoomWalls(buildRoomWalls(doc,"r1",0.12),"r2",0.12);
    expect(doc.walls).toHaveLength(7);
    expect(doc.walls.filter(w=>w.room_ids.length===2)).toHaveLength(1);
    const after=removeSpatialRoom(doc,"r1");
    expect(after.walls).toHaveLength(4);
    expect(after.walls.every(w=>w.room_ids.join()==="r2")).toBe(true);
  });
  it("部分共边会切分墙段，并保留原有开口的世界位置", () => {
    let doc=buildRoomWalls(document(),"r1",0.12);
    doc.rooms.push(rectangleRoom("r2","卧室",4,1,3,2,2.8));
    doc=buildRoomWalls(doc,"r2",0.12);
    expect(doc.walls.filter(w=>w.room_ids.length===2)).toHaveLength(1);
    expect(doc.walls).toHaveLength(8);
  });
});
describe("整屋保存恢复", () => {
  it("网络失败保留幂等键，重试成功才清除草稿", async () => {
    const storage=store();
    const save=vi.fn().mockRejectedValueOnce(new Error("网络中断")).mockImplementation(async (_id,p)=>({task_id:42,version:1,document:p.document}));
    const editor=new SpatialEditor(42, {get:async()=>({task_id:42,version:0,document:null}),save},storage);
    await editor.load(); editor.change(document()); await editor.save();
    expect(editor.snapshot.status).toBe("error"); expect(editor.snapshot.dirty).toBe(true);
    await editor.save();
    expect(save.mock.calls[0][1]).toEqual(save.mock.calls[1][1]);
    expect(editor.snapshot.version).toBe(1); expect(editor.snapshot.dirty).toBe(false);
  });
  it("冲突保留草稿与基准版本，不能静默覆盖远端", async () => {
    const storage=store(); const save=vi.fn().mockRejectedValue({status:409});
    const editor=new SpatialEditor(42,{get:async()=>({task_id:42,version:1,document:document()}),save},storage);
    await editor.load(); const changed=document(); changed.rooms[0].name="书房"; editor.change(changed); await editor.save();
    expect(editor.snapshot.status).toBe("conflict"); expect(editor.snapshot.document?.rooms[0].name).toBe("书房");
    const restored=new SpatialEditor(42,{get:async()=>({task_id:42,version:2,document:document()}),save},storage);
    await restored.load(); expect(restored.snapshot.status).toBe("conflict");
    expect(restored.snapshot.version).toBe(1);
  });
  it("读取失败不能建立空空间覆盖远端", async () => {
    const save=vi.fn(); const editor=new SpatialEditor(42,{get:async()=>{throw Error("离线");},save},store());
    await editor.load(); editor.change(document()); await editor.save();
    expect(save).not.toHaveBeenCalled(); expect(editor.snapshot.status).toBe("load-error");
  });
  it("撤销与重做不会改变服务端版本", async () => {
    const editor=new SpatialEditor(42,{get:async()=>({task_id:42,version:1,document:document()}),save:vi.fn()},store());
    await editor.load(); const next=document();next.rooms[0].name="卧室";editor.change(next);editor.undo();
    expect(editor.snapshot.dirty).toBe(false);editor.redo();expect(editor.snapshot.dirty).toBe(true);expect(editor.snapshot.version).toBe(1);
  });
});
