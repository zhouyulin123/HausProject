import { describe, expect, it } from "vitest";
import { objectRequirements, pointFromForm, clearanceBox } from "./homeDesignFields";
import { validHomeDraft } from "@/lib/homeDesignEditor";

describe("安装与点位人工输入", () => {
  it("点位默认未确认，坐标保持显式输入", () => {
    const form = new FormData();
    for (const [key,value] of Object.entries({name:"插座",room:"r",kind:"socket",x:"1",y:"0.3",z:"2"})) form.set(key,value);
    expect(pointFromForm(form,"p")).toEqual({id:"p",name:"插座",room_id:"r",kind:"socket",position:{x:1,y:0.3,z:2},confirmed:false});
  });
  it("未启用约束保留为空；冻结资产不可墙装", () => {
    expect(objectRequirements(new FormData(),false)).toEqual({installation:null,clearance:null,point_requirement:null});
    const form=new FormData();form.set("installation","wall");form.set("installation_wall","w");
    expect(()=>objectRequirements(form,true)).toThrow("落地");
  });
  it("安装与预留、连接距离仅来自显式字段",()=>{
    const form=new FormData();for(const [key,value] of Object.entries({installation:"wall",installation_wall:"w",clearance_enabled:"on",clearance_front:"0.5",clearance_back:"0",clearance_left:"0.1",clearance_right:"0.2",clearance_above:"0.3",point_requirement:"p",point_distance:"2"}))form.set(key,value);
    expect(objectRequirements(form,false)).toEqual({installation:{kind:"wall",wall_id:"w"},clearance:{front:0.5,back:0,left:0.1,right:0.2,above:0.3,confirmed:false},point_requirement:{point_id:"p",max_distance_m:2}});
    form.set("clearance_confirmed","on");expect(objectRequirements(form,false).clearance?.confirmed).toBe(true);
    form.set("clearance_above","");expect(()=>objectRequirements(form,false)).toThrow("数值");
  });
  it("墙装缺少宿主墙拒绝，空预留区不生成额外几何",()=>{
    const form=new FormData();form.set("installation","wall");expect(()=>objectRequirements(form,false)).toThrow("宿主墙");
    expect(clearanceBox({size:{width:1,height:1,depth:1}})).toBeNull();
  });
  it("本机草稿校验安装、预留与关联范围",()=>{
    const item={id:"o",name:"灯",room_id:"r",category:"lighting" as const,position:{x:1,y:1,z:1},size:{width:1,height:1,depth:1},rotation:0,material:{name:"金属",color:"#aabbcc"}};
    const base={schema_version:"home-design/1.0" as const,space_version:1,objects:[item],surfaces:[]};
    expect(validHomeDraft({...base,objects:[{...item,installation:{kind:"wall",wall_id:null}}]})).toBe(false);
    expect(validHomeDraft({...base,objects:[{...item,asset_id:2,installation:{kind:"ceiling",wall_id:null}}]})).toBe(false);
    expect(validHomeDraft({...base,objects:[{...item,clearance:{front:-1,back:0,left:0,right:0,above:0,confirmed:false}}]})).toBe(false);
    expect(validHomeDraft({...base,objects:[{...item,point_requirement:{point_id:"p",max_distance_m:101}}]})).toBe(false);
    expect(validHomeDraft({...base,objects:[{...item,installation:{kind:"wall",wall_id:"w"},point_requirement:{point_id:"p",max_distance_m:2},clearance:{front:1,back:0,left:0,right:0,above:0,confirmed:false}}]})).toBe(true);
  });
  it("预留区中心偏移和包围尺寸使用物件局部坐标", () => {
    expect(clearanceBox({size:{width:2,height:1,depth:1},clearance:{front:1,back:0.2,left:0.3,right:0.1,above:0.5,confirmed:false}})).toEqual({width:2.4,height:1.5,depth:2.2,x:-0.09999999999999999,y:0.75,z:0.4});
  });
  it("本机草稿拒绝非法点位和约束，旧格式保持兼容",()=>{
    const base={schema_version:"home-design/1.0" as const,space_version:1,objects:[],surfaces:[]};
    expect(validHomeDraft(base)).toBe(true);
    expect(validHomeDraft({...base,points:[null]} as never)).toBe(false);
    expect(validHomeDraft({...base,points:[{id:"p",name:"插座",room_id:"r",kind:"socket",position:{x:0,y:0,z:0},confirmed:"yes"}]} as never)).toBe(false);
  });
});
