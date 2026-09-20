import type { HomeAsset, HomeObject } from "@/types/homeDesign";
import { deterministicFurnitureRule } from "./deterministicFurniture";

export class HomeAssetCache {
  private values = new Map<number, Promise<HomeAsset>>();
  private active = 0;
  private queue: (() => void)[] = [];
  private completed = new Set<number>();
  constructor(readonly taskId: number, private fetch: (task: number, id: number) => Promise<HomeAsset>) {}
  invalidateRendered(id: number): void {
    if (this.completed.delete(id)) this.values.delete(id);
  }
  private async read(id: number): Promise<HomeAsset> {
    await new Promise<void>(resolve => {
      const start = () => {this.active++; resolve();};
      if (this.active < 4) start(); else this.queue.push(start);
    });
    try {return await this.fetch(this.taskId, id);}
    finally {this.active--; this.queue.shift()?.();}
  }
  get(id: number): Promise<HomeAsset> {
    const existing = this.values.get(id);
    if (existing) {
      if (this.completed.delete(id)) this.completed.add(id);
      return existing;
    }
    const result = this.read(id).then(asset => {
      if (asset.task_id !== this.taskId || asset.id !== id) throw Error("家具资产归属不匹配");
      this.completed.add(id);
      while (this.completed.size > 32) {
        const oldest = this.completed.values().next().value!;
        this.completed.delete(oldest); this.values.delete(oldest);
      }
      return asset;
    }).catch(error => { this.values.delete(id); throw error; });
    this.values.set(id, result);
    return result;
  }
}

export function homeAssetOffset(asset: HomeAsset): [number, number, number] {
  // 开放几何预览中心是已应用全局缩放的包围盒中心，渲染器内部负责缩放。
  const rule = deterministicFurnitureRule(asset.model_spec);
  if (rule?.生成器 !== "open_geometry_v1" && asset.kind !== "open_geometry") return [0,0,0];
  const center = (asset.model_spec.确定性建模规则 as {预览规则?: {中心_mm: number[]}} | undefined)?.预览规则?.中心_mm;
  if (!center || center.length !== 3 || !center.every(Number.isFinite)) throw Error("家具模型缺少可信中心");
  return [-center[0]/1000, asset.size.height/2-center[1]/1000, -center[2]/1000];
}

export function objectFromAsset(asset: HomeAsset, room: {id: string; polygon: {x: number; z: number}[]}): HomeObject {
  return {
    id: crypto.randomUUID(), asset_id: asset.id, room_id: room.id, name: asset.name, category: "furniture",
    position: {x: room.polygon.reduce((sum,p)=>sum+p.x,0)/room.polygon.length, y: 0, z: room.polygon.reduce((sum,p)=>sum+p.z,0)/room.polygon.length},
    size: {...asset.size}, material: {...asset.material}, rotation: 0,
  };
}
