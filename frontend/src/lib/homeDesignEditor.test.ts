import { describe, it, expect, vi } from "vitest";
import { HomeDesignEditor } from "./homeDesignEditor";
const space = {
  task_id: 1,
  version: 3,
  document: {
    schema_version: "spatial/1.0",
    unit: "m",
    scale_status: "confirmed",
    source_image_id: null,
    rooms: [
      {
        id: "r",
        name: "客厅",
        height: 2.8,
        polygon: [
          { x: 0, z: 0 },
          { x: 4, z: 0 },
          { x: 4, z: 4 },
          { x: 0, z: 4 },
        ],
      },
    ],
    walls: [],
    openings: [],
  },
} as const;
function setup() {
  const api = {
    get: vi.fn().mockResolvedValue({ task_id: 1, version: 0, document: null }),
    space: vi.fn().mockResolvedValue(space),
    spaceVersion: vi.fn().mockResolvedValue(space),
    save: vi.fn(),
  };
  return { api, editor: new HomeDesignEditor(1, api, null) };
}
function impactSetup() {
  const {api} = setup();
  const target = {...space.document,rooms:[{...space.document.rooms[0],id:"new-room",name:"新房间"}]};
  const impact = vi.fn().mockImplementation(async (_id,p) => ({task_id:1,source_space_version:p.document.space_version,target_space_version:p.target_space_version,target_space:target,candidate_document:{...p.document,space_version:p.target_space_version},changes:[],reference_issues:[],validation:{valid:true,issues:[]},can_apply:true}));
  api.space.mockResolvedValueOnce(space).mockResolvedValue({...space,version:4,document:target});
  const combined = {...api,impact};
  return {api:combined,editor:new HomeDesignEditor(1,combined,null),target};
}
describe("家装编辑状态", () => {
  it("候选点位解除仅修改关联且可撤销", async()=>{
    const {editor}=impactSetup();await editor.load();
    const item={id:"o",name:"设备",room_id:"r",category:"equipment" as const,position:{x:1,y:0,z:2},size:{width:1,height:1,depth:1},rotation:0,material:{name:"金属",color:"#aabbcc"},point_requirement:{point_id:"gone",max_distance_m:2}};
    editor.change({...editor.getSnapshot().document!,objects:[item]});await editor.previewSpaceImpact();
    await editor.resolveSpacePoint("o",null);
    expect(editor.getSnapshot().impact?.candidate_document.objects[0]).toEqual({...item,point_requirement:null});
    expect(editor.getSnapshot().document?.objects[0]).toEqual(item);
    editor.applySpaceImpact();editor.undo();expect(editor.getSnapshot().document?.objects[0]).toEqual(item);
  });
  it("人工迁移安装墙和点位只修改引用，保留坐标及使用要求",async()=>{
    const {api,editor,target}=impactSetup();await editor.load();
    const nextTarget={...target,walls:[{id:"new-wall",room_ids:["new-room"],start:{x:0,z:0},end:{x:4,z:0},height:2.8,thickness:0.1}]};
    api.impact.mockImplementation(async(_id,p)=>({task_id:1,source_space_version:p.document.space_version,target_space_version:4,target_space:nextTarget,candidate_document:{...p.document,space_version:4},changes:[],reference_issues:[],validation:{valid:true,issues:[]},can_apply:true}));
    const point={id:"p",name:"插座",room_id:"r",kind:"socket" as const,position:{x:1,y:0.3,z:0},confirmed:false};
    const object={id:"o",name:"壁灯",category:"lighting" as const,room_id:"r",position:{x:1,y:1,z:0.2},size:{width:0.3,height:0.3,depth:0.2},rotation:0,material:{name:"金属",color:"#aabbcc"},installation:{kind:"wall" as const,wall_id:"old-wall"},point_requirement:{point_id:"p",max_distance_m:2}};
    editor.change({...editor.getSnapshot().document!,points:[point],objects:[object]});await editor.previewSpaceImpact();
    await expect(editor.resolveSpaceReference("object","o",{roomId:"new-room"})).rejects.toThrow("墙体");
    await editor.resolveSpaceReference("object","o",{roomId:"new-room",wallId:"new-wall"});
    await editor.resolveSpaceReference("point","p",{roomId:"new-room"});
    expect(editor.getSnapshot().impact?.candidate_document.objects[0]).toEqual({...object,room_id:"new-room",installation:{kind:"wall",wall_id:"new-wall"}});
    expect(editor.getSnapshot().impact?.candidate_document.points?.[0]).toEqual({...point,room_id:"new-room"});
    editor.applySpaceImpact();editor.undo();expect(editor.getSnapshot().document?.points).toEqual([point]);editor.redo();expect(editor.getSnapshot().document?.points?.[0].room_id).toBe("new-room");
  });
  it("迟到预览不覆盖之后编辑的草稿", async () => {
    const {api,editor}=impactSetup(); await editor.load();
    let resolve!: (value: unknown)=>void;
    api.impact.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
    const preview=editor.previewSpaceImpact(); await Promise.resolve();
    editor.change({...editor.getSnapshot().document!,surfaces:[{id:"f",room_id:"r",kind:"floor",wall_id:null,material:{name:"木",color:"#aabbcc"}}]});
    resolve({}); await preview;
    expect(editor.getSnapshot().impact).toBeNull();
    expect(editor.getSnapshot().document?.surfaces).toHaveLength(1);
    expect(editor.getSnapshot().impactBusy).toBe(false);
  });
  it("较旧请求的错误不能清掉较新的成功预览",async()=>{
    const {api,editor}=impactSetup();await editor.load();let reject!:(error:Error)=>void;
    api.impact.mockImplementationOnce(()=>new Promise((_r,j)=>{reject=j;}));
    const first=editor.previewSpaceImpact();await Promise.resolve();await editor.previewSpaceImpact();reject(Error("旧请求断网"));await first;
    expect(editor.getSnapshot().impact?.target_space_version).toBe(4);expect(editor.getSnapshot().impactError).toBe("");
  });
  it("人工迁移物件保留位置尺寸材质资产，必须显式删除",async()=>{
    const {editor}=impactSetup();await editor.load();
    const item={id:"o",asset_id:9,name:"椅子",room_id:"r",category:"furniture" as const,position:{x:1,y:0,z:2},size:{width:1,height:1,depth:1},rotation:10,material:{name:"木",color:"#aabbcc"}};
    editor.change({...editor.getSnapshot().document!,objects:[item]});await editor.previewSpaceImpact();await editor.resolveSpaceReference("object","o",{roomId:"new-room"});expect(editor.getSnapshot().impact?.candidate_document.objects[0]).toEqual({...item,room_id:"new-room"});
    await editor.resolveSpaceReference("object","o","delete");expect(editor.getSnapshot().impact?.candidate_document.objects).toHaveLength(0);expect(editor.getSnapshot().document?.objects).toEqual([item]);
  });
  it("预览失败或错误版本保留当前空间和草稿", async () => {
    const {api,editor}=impactSetup(); await editor.load(); const original=editor.getSnapshot().document;
    api.impact.mockRejectedValueOnce(Error("断网")); await editor.previewSpaceImpact();
    expect(editor.getSnapshot().impactError).toBe("断网");
    expect(editor.getSnapshot().document).toEqual(original);
    api.impact.mockResolvedValueOnce({task_id:999});await editor.previewSpaceImpact();editor.applySpaceImpact();
    expect(editor.getSnapshot().impactError).toContain("版本不匹配");
    expect(editor.getSnapshot().space).toEqual(space.document);
  });
  it("保存待重试和冲突禁止更新户型", async () => {
    const {api,editor}=impactSetup(); await editor.load();api.save.mockRejectedValue({status:503});await editor.save();
    await editor.previewSpaceImpact();expect(api.impact).not.toHaveBeenCalled();
    api.save.mockRejectedValue({status:409});await editor.save();await editor.previewSpaceImpact();expect(api.impact).not.toHaveBeenCalled();
  });
  it("人工处理只改候选并重新预览，原空间和饰面保持不变", async () => {
    const {api,editor}=impactSetup();await editor.load();
    editor.change({...editor.getSnapshot().document!,surfaces:[{id:"f",room_id:"r",kind:"floor",wall_id:null,material:{name:"木",color:"#aabbcc"}}]});
    await editor.previewSpaceImpact();await editor.resolveSpaceReference("surface","f",{roomId:"new-room"});
    expect(api.impact.mock.lastCall?.[1].document.surfaces[0].room_id).toBe("new-room");
    expect(editor.getSnapshot().document?.surfaces[0].room_id).toBe("r");
    await editor.resolveSpaceReference("surface","f","delete");expect(editor.getSnapshot().impact?.candidate_document.surfaces).toHaveLength(0);
    expect(editor.getSnapshot().document?.surfaces).toHaveLength(1);
  });
  it("人工处理失败保留上次候选并禁止应用，允许继续修正",async()=>{
    const {api,editor}=impactSetup();await editor.load();await editor.previewSpaceImpact();const previous=editor.getSnapshot().impact;
    api.impact.mockRejectedValueOnce(Error("校验暂不可用"));await editor.resolveSpaceReference("object","absent","delete");
    expect(editor.getSnapshot().impact).toEqual(previous);editor.applySpaceImpact();expect(editor.getSnapshot().document?.space_version).toBe(3);
    await editor.resolveSpaceReference("object","absent","delete");editor.applySpaceImpact();expect(editor.getSnapshot().document?.space_version).toBe(4);
  });
  it("缺失引用禁止应用，墙面归属必须明确且有效", async () => {
    const {editor}=impactSetup();await editor.load();editor.change({...editor.getSnapshot().document!,surfaces:[{id:"w",room_id:"r",kind:"wall",wall_id:"old-wall",material:{name:"木",color:"#aabbcc"}}]});
    await editor.previewSpaceImpact();await expect(editor.resolveSpaceReference("surface","w",{roomId:"new-room",wallId:"bad"})).rejects.toThrow("墙体");
    const impact=editor.getSnapshot().impact!;impact.can_apply=false;editor.applySpaceImpact();expect(editor.getSnapshot().document?.space_version).toBe(3);
    await expect(editor.resolveSpaceReference("surface","w",{roomId:"absent"})).rejects.toThrow("房间");
  });
  it("新空间未保存草稿刷新后读取精确空间版本", async () => {
    const {api,target}=impactSetup();
    const storage={value:null as string|null,getItem(){return this.value;},setItem(_k:string,v:string){this.value=v;},removeItem(){this.value=null;}};
    const original={schema_version:"home-design/1.0",space_version:3,surfaces:[],objects:[]};api.get.mockResolvedValue({task_id:1,version:1,document:original});
    const editor=new HomeDesignEditor(1,api,storage);await editor.load();
    api.space.mockReset().mockResolvedValue({...space,version:4,document:target});await editor.previewSpaceImpact();editor.applySpaceImpact();
    api.spaceVersion.mockResolvedValue({...space,version:4,document:target});
    const restored=new HomeDesignEditor(1,api,storage);await restored.load();expect(api.spaceVersion).toHaveBeenLastCalledWith(1,4);expect(restored.getSnapshot().dirty).toBe(true);expect(restored.getSnapshot().space).toEqual(target);
  });
  it("更新户型预览保留原方案，载入后跨空间撤销重做", async () => {
    const { api } = setup();
    const target = { ...space.document, rooms: [{ ...space.document.rooms[0], name: "新客厅" }] };
    const impact = vi.fn().mockImplementation(async (_id, p) => ({task_id:1,source_space_version:3,target_space_version:4,target_space:target,candidate_document:{...p.document,space_version:4},changes:[],reference_issues:[],validation:{valid:true,issues:[]},can_apply:true}));
    const editor = new HomeDesignEditor(1, {...api, impact}, null);
    await editor.load();
    api.space.mockResolvedValue({...space,version:4,document:target});
    await editor.previewSpaceImpact();
    expect(editor.getSnapshot().document?.space_version).toBe(3);
    editor.applySpaceImpact();
    expect(editor.getSnapshot().document?.space_version).toBe(4);
    expect(editor.getSnapshot().space?.rooms[0].name).toBe("新客厅");
    editor.undo();
    expect(editor.getSnapshot().document?.space_version).toBe(3);
    expect(editor.getSnapshot().space?.rooms[0].name).toBe("客厅");
    editor.redo();
    expect(editor.getSnapshot().document?.space_version).toBe(4);
    expect(editor.getSnapshot().dirty).toBe(true);
  });
  it('空方案首次保存断网后刷新仍重试原幂等键',async()=>{const {api}=setup();const storage={value:null as string|null,getItem(){return this.value;},setItem(_k:string,v:string){this.value=v;},removeItem(){this.value=null;}};const first=new HomeDesignEditor(1,api,storage);await first.load();api.save.mockRejectedValue(Error('断网'));await first.save();const payload=api.save.mock.calls[0][1];const second=new HomeDesignEditor(1,api,storage);await second.load();expect(second.getSnapshot().status).toBe('error');await second.save();expect(api.save.mock.calls[1][1]).toEqual(payload);});
  it("过期历史读取不覆盖较新的重新载入", async () => {
    const { api, editor } = setup();
    await editor.load();
    let resolve!: (value: unknown) => void;
    api.spaceVersion.mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const old = editor.restore({
      task_id: 1,
      version: 1,
      document: {
        schema_version: "home-design/1.0",
        space_version: 3,
        surfaces: [],
        objects: [],
      },
    });
    await editor.load(true);
    resolve(space);
    await old;
    expect(editor.getSnapshot().message).not.toContain("历史版本");
  });
  it("读取失败保留数据但不得表示同步成功", async () => {
    const { api, editor } = setup();
    await editor.load();
    api.get.mockRejectedValue(Error("断网"));
    await editor.load();
    expect(editor.getSnapshot().status).toBe("load-error");
    expect(editor.editable).toBe(false);
  });
  it("首次空文档可直接保存", async () => {
    const { api, editor } = setup();
    await editor.load();
    api.save.mockResolvedValue({
      task_id: 1,
      version: 1,
      document: editor.getSnapshot().document,
    });
    await editor.save();
    expect(api.save).toHaveBeenCalled();
  });
  it("读取失败不可编辑，不创造空方案", async () => {
    const { api, editor } = setup();
    api.get.mockRejectedValue(Error("断网"));
    await editor.load();
    expect(editor.getSnapshot().status).toBe("load-error");
    expect(editor.editable).toBe(false);
  });
  it("空设计绑定已确认空间版本", async () => {
    const { editor } = setup();
    await editor.load();
    expect(editor.getSnapshot().document?.space_version).toBe(3);
    expect(editor.editable).toBe(true);
  });
  it("修改可撤销和重做", async () => {
    const { editor } = setup();
    await editor.load();
    editor.change({
      ...editor.getSnapshot().document!,
      surfaces: [
        {
          id: "f",
          room_id: "r",
          kind: "floor",
          wall_id: null,
          material: { name: "木", color: "#aabbcc" },
        },
      ],
    });
    editor.undo();
    expect(editor.getSnapshot().document?.surfaces).toHaveLength(0);
    editor.redo();
    expect(editor.getSnapshot().document?.surfaces).toHaveLength(1);
  });
  it("失败重试使用同一请求，冲突保留草稿", async () => {
    const { api, editor } = setup();
    await editor.load();
    editor.change({
      ...editor.getSnapshot().document!,
      surfaces: [
        {
          id: "f",
          room_id: "r",
          kind: "floor",
          wall_id: null,
          material: { name: "木", color: "#aabbcc" },
        },
      ],
    });
    api.save
      .mockRejectedValueOnce(Error("断网"))
      .mockRejectedValueOnce({ status: 409 });
    await editor.save();
    await editor.save();
    expect(api.save.mock.calls[0][1]).toEqual(api.save.mock.calls[1][1]);
    expect(editor.getSnapshot().status).toBe("conflict");
    expect(editor.getSnapshot().dirty).toBe(true);
  });
  it("已有设计读取精确空间而非最新空间", async () => {
    const { api, editor } = setup();
    api.get.mockResolvedValue({
      task_id: 1,
      version: 2,
      document: {
        schema_version: "home-design/1.0",
        space_version: 3,
        surfaces: [],
        objects: [],
      },
    });
    await editor.load();
    expect(api.spaceVersion).toHaveBeenCalledWith(1, 3);
    expect(api.space).not.toHaveBeenCalled();
  });
  it("尺度未确认阻止编辑", async () => {
    const { api, editor } = setup();
    api.space.mockResolvedValue({
      ...space,
      document: { ...space.document, scale_status: "unconfirmed" },
    });
    await editor.load();
    expect(editor.getSnapshot().status).toBe("blocked");
  });
  it("恢复草稿和幂等请求并保存几何风险", async () => {
    const { api } = setup();
    const document = {
      schema_version: "home-design/1.0",
      space_version: 3,
      surfaces: [],
      objects: [],
    };
    const pending = { base_version: 1, client_mutation_id: "retry", document };
    const storage = {
      getItem: vi
        .fn()
        .mockReturnValue(
          JSON.stringify({ base_version: 1, document, pending }),
        ),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    };
    api.get.mockResolvedValue({
      task_id: 1,
      version: 1,
      document: { ...document, surfaces: [{ id: "a" }] },
    });
    api.save.mockResolvedValue({
      task_id: 1,
      version: 2,
      document,
      validation: {
        valid: false,
        issues: [{ code: "collision", message: "碰撞", object_ids: [] }],
      },
    });
    const editor = new HomeDesignEditor(1, api, storage);
    await editor.load();
    expect(editor.getSnapshot().status).toBe("error");
    await editor.save();
    expect(api.save).toHaveBeenCalledWith(1, pending);
    expect(editor.getSnapshot().validation?.valid).toBe(false);
    expect(editor.getSnapshot().dirty).toBe(false);
    expect(storage.removeItem).toHaveBeenCalled();
  });
  it("422允许修正，409不可继续改写", async () => {
    const { api, editor } = setup();
    await editor.load();
    editor.change({
      ...editor.getSnapshot().document!,
      surfaces: [
        {
          id: "f",
          room_id: "r",
          kind: "floor",
          wall_id: null,
          material: { name: "木", color: "#aabbcc" },
        },
      ],
    });
    api.save.mockRejectedValue({
      status: 422,
      detail: { message: "字段无效" },
    });
    await editor.save();
    expect(editor.editable).toBe(true);
    expect(editor.getSnapshot().message).toBe("字段无效");
    api.save.mockRejectedValue({ status: 409 });
    await editor.save();
    expect(editor.editable).toBe(false);
  });
  it("不接受错误空间版本响应", async () => {
    const { api, editor } = setup();
    api.get.mockResolvedValue({
      task_id: 1,
      version: 2,
      document: {
        schema_version: "home-design/1.0",
        space_version: 2,
        surfaces: [],
        objects: [],
      },
    });
    await editor.load();
    expect(editor.getSnapshot().status).toBe("load-error");
    expect(editor.getSnapshot().document).toBeNull();
  });
  it("历史载入不修改服务器家装基准版本", async () => {
    const { api, editor } = setup();
    await editor.load();
    await editor.restore({
      task_id: 1,
      version: 8,
      document: {
        schema_version: "home-design/1.0",
        space_version: 3,
        surfaces: [
          {
            id: "f",
            room_id: "r",
            kind: "floor",
            wall_id: null,
            material: { name: "木", color: "#aabbcc" },
          },
        ],
        objects: [],
      },
    });
    expect(editor.getSnapshot().version).toBe(0);
    expect(editor.getSnapshot().dirty).toBe(true);
    expect(api.save).not.toHaveBeenCalled();
  });
});
