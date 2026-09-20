import {it,expect,vi} from "vitest";
import {HomeQuoteController} from "./homeQuote";
it("确定性参数拒绝允许修正地区，503仍保留请求",async()=>{
  const api={create:vi.fn().mockRejectedValueOnce({status:422}).mockRejectedValue({status:503}),list:vi.fn()};const c=new HomeQuoteController(2,3,api);await c.create("CN-XX");expect(c.getSnapshot().pending).toBeNull();await c.create("CN-SH");expect(c.getSnapshot().pending?.region).toBe("CN-SH");
});
it("订阅清理与损坏重试记录明确失败，存储失败不阻止服务端结果",async()=>{
  const api={create:vi.fn().mockResolvedValue({id:1,task_id:2,home_version:3,snapshot:{}}),list:vi.fn().mockResolvedValue({items:[],next_before_id:null})};
  const c=new HomeQuoteController(2,3,api,{getItem:()=>"broken",setItem:()=>{throw Error();},removeItem:()=>{throw Error();}});expect(c.getSnapshot().error).toContain("无效");const listener=vi.fn();const unsubscribe=c.subscribe(listener);await c.create("CN-SH");expect(listener).toHaveBeenCalled();unsubscribe();const count=listener.mock.calls.length;await c.load();expect(listener).toHaveBeenCalledTimes(count);expect(c.getSnapshot().selected?.id).toBe(1);
});
it("刷新恢复待重试请求而不是创建新幂等键",async()=>{
  const storage={value:null as string|null,getItem(){return this.value;},setItem(_key:string,value:string){this.value=value;},removeItem(){this.value=null;}};
  const api={create:vi.fn().mockRejectedValueOnce(Error("503")).mockResolvedValue({id:1,task_id:2,home_version:3,snapshot:{}}),list:vi.fn().mockResolvedValue({items:[],next_before_id:null})};
  const first=new HomeQuoteController(2,3,api,storage);await first.create("CN-SH");
  const second=new HomeQuoteController(2,3,api,storage);await second.load();await second.retry();expect(api.create.mock.calls[0]).toEqual(api.create.mock.calls[1]);expect(storage.value).toBeNull();
});
it("关闭后迟到创建不覆盖状态，原请求仍可恢复",async()=>{
  let resolve!:(value:unknown)=>void;const api={create:vi.fn(()=>new Promise(r=>{resolve=r;})),list:vi.fn()};const c=new HomeQuoteController(2,3,api as never);const pending=c.create("CN-SH");c.dispose();resolve({id:1,task_id:2,home_version:3,snapshot:{}});await pending;expect(c.getSnapshot().selected).toBeNull();expect(c.getSnapshot().pending).not.toBeNull();
});
it("历史校验失败保留原快照，分页不重复",async()=>{
  const row={id:1,task_id:2,home_version:3,snapshot:{}};const api={create:vi.fn(),list:vi.fn().mockResolvedValueOnce({items:[row],next_before_id:1}).mockResolvedValueOnce({items:[row,{...row,id:2}],next_before_id:null}).mockResolvedValue({items:[{...row,home_version:4}],next_before_id:null})};
  const c=new HomeQuoteController(2,3,api);await c.load();await c.load(true);expect(c.getSnapshot().items).toHaveLength(2);c.select(2);await c.load();expect(c.getSnapshot().selected?.id).toBe(2);expect(c.getSnapshot().error).toContain("版本");
});
it("地区不猜测，重复点击与未解决请求不重复创建",async()=>{
  const api={create:vi.fn().mockRejectedValue(Error("断网")),list:vi.fn()};const c=new HomeQuoteController(2,3,api);await c.create("上海");expect(api.create).not.toHaveBeenCalled();await c.create("CN-SH");await c.create("CN-BJ");expect(api.create).toHaveBeenCalledTimes(1);expect(c.getSnapshot().pending?.region).toBe("CN-SH");
});
it("估价失败保留请求，重试沿用同键且拒绝串版本结果",async()=>{
  const api={create:vi.fn().mockRejectedValueOnce(Error("断网")).mockResolvedValue({id:1,task_id:2,home_version:3,snapshot:{}}),list:vi.fn().mockResolvedValue({items:[],next_before_id:null})};
  const controller=new HomeQuoteController(2,3,api);
  await controller.create("CN-SH");expect(controller.getSnapshot().pending).not.toBeNull();
  await controller.retry();expect(api.create.mock.calls[0]).toEqual(api.create.mock.calls[1]);expect(controller.getSnapshot().selected?.id).toBe(1);
  api.create.mockResolvedValue({id:2,task_id:99,home_version:3,snapshot:{}});
  await controller.create("CN-SH");expect(controller.getSnapshot().error).toContain("版本");expect(controller.getSnapshot().selected?.id).toBe(1);
});
it("刷新历史只恢复当前精确版本",async()=>{
  const api={create:vi.fn(),list:vi.fn().mockResolvedValue({items:[{id:1,task_id:2,home_version:3,snapshot:{}}],next_before_id:null})};
  const controller=new HomeQuoteController(2,3,api);await controller.load();expect(controller.getSnapshot().selected?.id).toBe(1);
  expect(api.list).toHaveBeenCalledWith(2,3,undefined);
});
