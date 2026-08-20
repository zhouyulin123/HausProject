import type { DesignPlan } from "@/types/design";
import type { FurnitureItem } from "@/types/furniture";

/** 3D 场景中的一件家具（单位：米，坐标系原点在房间中心，y=0 为地面） */
export interface LayoutItem {
  id: string;
  name: string;
  category: string;
  /** [宽, 高, 深] */
  size: [number, number, number];
  /** [x, y, z]，y 为物体中心高度 */
  position: [number, number, number];
  /** 绕 Y 轴旋转（弧度） */
  rotationY: number;
  color: string;
}

export interface RoomScene {
  roomType: string;
  width: number;
  depth: number;
  height: number;
  items: LayoutItem[];
}

// 房间尺寸（米）按空间类型给默认值
const ROOM_SIZE: Record<string, [number, number]> = {
  客厅: [4.6, 5.6],
  卧室: [3.6, 4.2],
  餐厅: [3.6, 3.8],
  书房: [3.0, 3.6],
  厨房: [2.8, 3.6],
  儿童房: [3.2, 3.8],
};

// 家具高度默认值（米）
const CATEGORY_HEIGHT: Record<string, number> = {
  沙发: 0.85,
  茶几: 0.42,
  柜子: 1.9,
  床: 0.5,
  餐桌: 0.75,
  餐椅: 0.9,
  书桌: 0.75,
  书椅: 0.95,
  灯具: 1.5,
  窗帘: 2.4,
  地毯: 0.02,
};

// 家具默认占地（米）[宽, 深]
const CATEGORY_FOOTPRINT: Record<string, [number, number]> = {
  沙发: [2.2, 0.95],
  茶几: [1.0, 0.55],
  柜子: [1.6, 0.4],
  床: [1.8, 2.0],
  餐桌: [1.3, 0.8],
  餐椅: [0.5, 0.5],
  书桌: [1.4, 0.7],
  书椅: [0.6, 0.6],
  灯具: [0.4, 0.4],
  窗帘: [1.6, 0.1],
  地毯: [2.0, 2.9],
};

// 家具配色（暖色调）
const CATEGORY_COLOR: Record<string, string> = {
  沙发: "#D8C7A8",
  茶几: "#A6835B",
  柜子: "#CDB68F",
  床: "#DAC9AC",
  餐桌: "#A6835B",
  餐椅: "#B89A6D",
  书桌: "#B08F63",
  书椅: "#9C8467",
  灯具: "#E8D9A8",
  窗帘: "#E5DCC6",
  地毯: "#B7A98C",
};

/** 从"宽 2.4m x 深 1.05m"/"直径 0.8m"等文本提取尺寸；失败返回 null */
function parseSize(text: string | undefined): [number, number] | null {
  if (!text) return null;
  const nums = [...text.matchAll(/(\d+(?:\.\d+)?)\s*m/gi)].map((m) => Number(m[1]));
  const valid = nums.filter((n) => n > 0.1 && n < 6);
  if (valid.length >= 2) return [valid[0], valid[1]];
  if (valid.length === 1) return [valid[0], valid[0]]; // 直径类
  return null;
}

function footprint(item: FurnitureItem): [number, number] {
  const model = item.modelDimensionsMm;
  if (
    item.modelStatus === "ready" &&
    model?.width &&
    model.depth &&
    model.width > 0 &&
    model.depth > 0
  ) {
    return [model.width / 1000, model.depth / 1000];
  }
  return (
    parseSize(item.sizeSuggestion) ??
    CATEGORY_FOOTPRINT[item.category] ?? [1.0, 0.8]
  );
}

const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

/**
 * 规则式布局：把方案中属于目标空间的家具摆进一个矩形房间。
 * 沙发靠后墙、茶几在沙发前、柜子靠前墙、地毯居中平铺、灯具落角，
 * 其余家具沿侧墙依次排布。后续可替换为 LLM 生成 + 碰撞校验。
 * size 为可选的真实房间尺寸（米），缺省时按空间类型使用默认值。
 */
export function computeRoomLayout(
  plan: DesignPlan,
  roomType: string,
  size?: { width: number; depth: number },
): RoomScene {
  const fallback = ROOM_SIZE[roomType] ?? [4.4, 5.2];
  const [width, depth] =
    size && size.width > 0 && size.depth > 0 ? [size.width, size.depth] : fallback;
  const height = 2.8;

  // 只取属于该空间的家具；没有匹配则全取
  const all = plan.furnitureSuggestions ?? [];
  let items = all.filter((f) => f.room === roomType);
  if (items.length === 0) items = all;

  const layout: LayoutItem[] = [];
  const halfW = width / 2;
  const halfD = depth / 2;

  // 侧墙排布游标（左墙从后往前）
  let leftCursor = -halfD + 0.5;

  const push = (
    item: FurnitureItem,
    w: number,
    d: number,
    x: number,
    z: number,
    rotationY: number,
  ) => {
    const modelHeight = item.modelDimensionsMm?.height;
    const h =
      item.modelStatus === "ready" && modelHeight && modelHeight > 0
        ? modelHeight / 1000
        : CATEGORY_HEIGHT[item.category] ?? 0.8;
    layout.push({
      id: item.sku ?? item.id,
      name: item.name,
      category: item.category,
      size: [w, h, d],
      position: [x, h / 2, z],
      rotationY,
      color: CATEGORY_COLOR[item.category] ?? "#C3B49A",
    });
  };

  // 记录已用主位，避免沙发/柜子等主家具重叠
  let sofaZ: number | null = null;

  for (const item of items) {
    const [fw, fd] = footprint(item);
    const cat = item.category;

    if (cat === "沙发" && sofaZ === null) {
      const z = -halfD + fd / 2 + 0.15;
      sofaZ = z;
      push(item, fw, fd, 0, z, 0);
    } else if (cat === "茶几") {
      const z = (sofaZ ?? -halfD + 1) + 1.25;
      push(item, fw, fd, 0, clamp(z, -halfD + 0.5, halfD - 0.5), 0);
    } else if (cat === "地毯") {
      const z = (sofaZ ?? 0) + 1.1;
      layout.push({
        id: item.sku ?? item.id,
        name: item.name,
        category: cat,
        size: [fw, 0.03, fd],
        position: [0, 0.015, clamp(z, -halfD + fd / 2, halfD - fd / 2)],
        rotationY: 0,
        color: CATEGORY_COLOR[cat],
      });
    } else if (cat === "柜子") {
      // 靠前墙，面向沙发
      push(item, fw, fd, 0, halfD - fd / 2 - 0.15, Math.PI);
    } else if (cat === "床") {
      // 靠左墙居中
      push(item, fd, fw, -halfW + fd / 2 + 0.15, 0, Math.PI / 2);
    } else if (cat === "灯具") {
      // 右后角
      push(item, fw, fd, halfW - fw / 2 - 0.35, -halfD + fd / 2 + 0.35, 0);
    } else if (cat === "餐桌" || cat === "书桌") {
      push(item, fw, fd, 0, 0, 0);
    } else {
      // 其余沿左墙依次排布
      const z = clamp(leftCursor + fd / 2, -halfD + 0.4, halfD - 0.4);
      push(item, fw, fd, -halfW + fw / 2 + 0.2, z, 0);
      leftCursor += fd + 0.3;
    }
  }

  return { roomType, width, depth, height, items: layout };
}
