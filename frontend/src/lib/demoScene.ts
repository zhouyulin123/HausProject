import type { FurnitureItem } from "@/types/furniture";
import type { SceneOperation } from "@/types/scene";

/** 程序化模型以底部或吸顶点为原点，按显式商品元数据选择渲染高度。 */
export function demoItemRenderY(
  furniture: FurnitureItem,
  ceilingHeight: number,
): number {
  return furniture.modelSpecJson?.安装参数?.锚点 === "ceiling"
    ? ceilingHeight
    : 0;
}

/** 汇总本轮实际受影响实例，供“刚才那个”一类跨轮指代使用。 */
export function findAffectedInstanceIds(
  beforeIds: string[],
  afterIds: string[],
  operations: SceneOperation[],
): string[] {
  const before = new Set(beforeIds);
  const affected = new Set(
    operations.flatMap((operation) =>
      "instanceId" in operation ? [operation.instanceId] : [],
    ),
  );
  for (const instanceId of afterIds) {
    if (!before.has(instanceId)) affected.add(instanceId);
  }
  return [...affected];
}
