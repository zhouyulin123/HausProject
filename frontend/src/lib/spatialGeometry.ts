import type { SpatialDocument,SpatialPoint,SpatialRoom,SpatialWall } from "@/types/spatial";
const EPS=1e-7;
export const spatialId=() => crypto.randomUUID();
export const emptySpatialDocument=(): SpatialDocument => ({ schema_version: "spatial/1.0",unit: "m",scale_status: "unconfirmed",source_image_id: null,rooms: [],walls: [],openings: [] });
export const distance=(a: SpatialPoint,b: SpatialPoint) => Math.hypot(b.x-a.x,b.z-a.z);
export function updateSpatialRoom(document: SpatialDocument,room: SpatialRoom): SpatialDocument {
  if(document.walls.some(w => w.room_ids.includes(room.id)&&w.height>room.height+EPS))
    throw Error("层高低于已有墙体，请先调整墙体高度");
  return { ...document,rooms: document.rooms.map(r => r.id===room.id? room:r),scale_status: "unconfirmed" };
}
export function roomArea(room: SpatialRoom): number {
  return Math.abs(room.polygon.reduce((sum,p,i) => { const q=room.polygon[(i+1)%room.polygon.length]; return sum+p.x*q.z-q.x*p.z; },0))/2;
}
export function rectangleRoom(id: string,name: string,x: number,z: number,width: number,depth: number,height: number): SpatialRoom {
  if(![x,z,width,depth,height].every(Number.isFinite)||width<=0||depth<=0||height<=1.8||height>8||!name.trim())
    throw Error("请填写有效的房间名称、尺寸和层高");
  return { id,name: name.trim(),height,polygon: [{ x,z },{ x: x+width,z },{ x: x+width,z: z+depth },{ x,z: z+depth }] };
}
export function spatialBounds(document: SpatialDocument) {
  const points=document.rooms.flatMap(r => r.polygon);
  const reference=document.image_reference;
  if(reference)
    points.push(reference.origin,{ x: reference.origin.x+reference.width,z: reference.origin.z+reference.depth });
  if(!points.length)
    return { minX: -1,minZ: -1,width: 10,depth: 8 };
  const minX=Math.min(...points.map(p => p.x)),minZ=Math.min(...points.map(p => p.z));
  return { minX,minZ,width: Math.max(1,Math.max(...points.map(p => p.x))-minX),depth: Math.max(1,Math.max(...points.map(p => p.z))-minZ) };
}
export function scaleSpatialDocument(document: SpatialDocument,factor: number): SpatialDocument {
  if(!Number.isFinite(factor)||factor<=0||factor>1000)
    throw Error("缩放比例必须大于 0");
  const point=(p: SpatialPoint) => ({ x: p.x*factor,z: p.z*factor });
  return {
    ...document,scale_status: "unconfirmed",image_reference: document.image_reference? { origin: point(document.image_reference.origin),width: document.image_reference.width*factor,depth: document.image_reference.depth*factor }:null,rooms: document.rooms.map(r => ({ ...r,polygon: r.polygon.map(point) })),
    walls: document.walls.map(w => ({ ...w,start: point(w.start),end: point(w.end),thickness: w.thickness*factor })),
    openings: document.openings.map(o => ({ ...o,offset: o.offset*factor,width: o.width*factor }))
  };
}
export function removeRoomWalls(document: SpatialDocument,roomId: string): SpatialDocument {
  const walls=document.walls.map(w => ({ ...w,room_ids: w.room_ids.filter(id => id!==roomId) })).filter(w => w.room_ids.length);
  return { ...document,walls,openings: document.openings.filter(o => walls.some(w => w.id===o.wall_id)) };
}
export function removeSpatialRoom(document: SpatialDocument,roomId: string): SpatialDocument {
  return { ...removeRoomWalls(document,roomId),rooms: document.rooms.filter(r => r.id!==roomId),scale_status: "unconfirmed" };
}
const cross=(a: SpatialPoint,b: SpatialPoint,p: SpatialPoint) => (b.x-a.x)*(p.z-a.z)-(b.z-a.z)*(p.x-a.x);
const pointAt=(w: SpatialWall,t: number) => ({ x: w.start.x+(w.end.x-w.start.x)*t,z: w.start.z+(w.end.z-w.start.z)*t });
const fraction=(w: SpatialWall,p: SpatialPoint) => ((p.x-w.start.x)*(w.end.x-w.start.x)+(p.z-w.start.z)*(w.end.z-w.start.z))/(distance(w.start,w.end)**2);
const same=(a: SpatialPoint,b: SpatialPoint) => distance(a,b)<EPS;
/** 按所有共线端点切分墙段；开口若跨新分段，拒绝修改而不是截断开口。 */
export function buildRoomWalls(document: SpatialDocument,roomId: string,thickness: number): SpatialDocument {
  if(!Number.isFinite(thickness)||thickness<=0||thickness>1)
    throw Error("墙厚须为 0 到 1 米之间");
  const room=document.rooms.find(r => r.id===roomId);
  if(!room)
    throw Error("房间不存在");
  const added=room.polygon.map((start,i): SpatialWall => ({ id: spatialId(),start,end: room.polygon[(i+1)%room.polygon.length],room_ids: [roomId],height: room.height,thickness }));
  const inputs=[...document.walls,...added];
  if(inputs.some(w => distance(w.start,w.end)<EPS))
    throw Error("轮廓存在重复顶点");
  const walls: SpatialWall[]=[];
  for(const original of inputs) {
    const cuts=[0,1];
    for(const other of inputs) {
      if(Math.abs(cross(original.start,original.end,other.start))>EPS||Math.abs(cross(original.start,original.end,other.end))>EPS)
        continue;
      for(const p of [other.start,other.end]) {
        const t=fraction(original,p);
        if(t>EPS&&t<1-EPS)
          cuts.push(t);
      }
    }
    const sorted=[...new Set(cuts.map(t => Math.round(t*1e10)/1e10))].sort((a,b) => a-b);
    for(let i=0;i<sorted.length-1;i++) {
      const start=pointAt(original,sorted[i]),end=pointAt(original,sorted[i+1]);
      const existing=walls.find(w => (same(w.start,start)&&same(w.end,end))||(same(w.end,start)&&same(w.start,end)));
      if(existing) {
        if(Math.abs(existing.thickness-original.thickness)>EPS)
          throw Error("共享墙的墙厚不一致，请使用已有墙厚");
        existing.room_ids=[...new Set([...existing.room_ids,...original.room_ids])];
        if(existing.room_ids.length>2)
          throw Error("同一墙段不能连接超过两个房间");
        existing.height=Math.min(existing.height,original.height);
      }
      else
        walls.push({ ...original,id: i===0? original.id:spatialId(),start,end,room_ids: [...original.room_ids] });
    }
  }
  const openings=document.openings.map(opening => {
    const old=document.walls.find(w => w.id===opening.wall_id)!;
    const length=distance(old.start,old.end);
    const start=pointAt(old,opening.offset/length),end=pointAt(old,(opening.offset+opening.width)/length);
    const wall=walls.find(w => Math.abs(cross(w.start,w.end,start))<EPS&&Math.abs(cross(w.start,w.end,end))<EPS&&
      Math.min(fraction(w,start),fraction(w,end))>=-EPS&&Math.max(fraction(w,start),fraction(w,end))<=1+EPS);
    if(!wall)
      throw Error("门窗跨越了新的墙段分界，请先调整该门窗");
    return { ...opening,wall_id: wall.id,offset: Math.max(0,Math.min(fraction(wall,start),fraction(wall,end))*distance(wall.start,wall.end)) };
  });
  return { ...document,walls,openings };
}
export function validateSpatialDraft(document: SpatialDocument): string|null {
  if(document.schema_version!=="spatial/1.0"||document.unit!=="m"||!Array.isArray(document.rooms)||!Array.isArray(document.walls)||!Array.isArray(document.openings))
    return "空间文件格式无效";
  if(document.rooms.length>50||document.walls.length>500||document.openings.length>500)
    return "空间对象数量超过限制";
  if(document.image_reference) {
    const frame=document.image_reference;
    if(!document.source_image_id||!frame.origin||![frame.origin.x,frame.origin.z,frame.width,frame.depth].every(Number.isFinite)||frame.width<=0||frame.depth<=0||frame.width>10000||frame.depth>10000)
      return "底图坐标框无效";
  }
  for(const r of document.rooms) {
    if(!r.id||!r.name?.trim()||!Array.isArray(r.polygon)||r.polygon.length<3||r.polygon.length>100||!Number.isFinite(r.height)||r.height<=1.8||r.height>8)
      return "房间名称、轮廓或层高无效";
    if(r.polygon.some(p => !Number.isFinite(p.x)||!Number.isFinite(p.z)||Math.abs(p.x)>10000||Math.abs(p.z)>10000)||roomArea(r)<1e-6)
      return "房间轮廓需要围成有效面积";
    if(r.polygon.some((p,i) => distance(p,r.polygon[(i+1)%r.polygon.length])<1e-6))
      return "房间轮廓存在重复顶点";
  }
  for(const w of document.walls)
    if(!w.start||!w.end||![w.start.x,w.start.z,w.end.x,w.end.z,w.height,w.thickness].every(Number.isFinite)||distance(w.start,w.end)<1e-6||w.height<=0||w.thickness<=0||w.thickness>1||!Array.isArray(w.room_ids)||!w.room_ids.length||w.room_ids.some(id => !document.rooms.some(r => r.id===id)))
      return "墙体尺寸或房间引用无效";
  for(const o of document.openings) {
    const wall=document.walls.find(w => w.id===o.wall_id);
    if(!wall||![o.offset,o.width,o.height,o.sill_height].every(Number.isFinite)||o.offset<0||o.width<=0||o.height<=0||o.sill_height<0||o.offset+o.width>distance(wall.start,wall.end)+EPS||o.sill_height+o.height>wall.height+EPS)
      return "门窗尺寸超出墙体范围";
  }
  return null;
}
