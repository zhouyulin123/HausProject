import type { SceneDocument, SceneItem } from "@/types/scene";
import type { FurnitureItem } from "@/types/furniture";

export type SpaceName = "客厅" | "卧室" | "餐厅";
export type StyleName = "奶油风" | "原木风" | "现代简约" | "轻法式";

export type HeroSelectPayload = {
  name: string;
  category: string;
  tip: string;
} | null;

export const SPACES: SpaceName[] = ["客厅", "卧室", "餐厅"];
export const STYLES: StyleName[] = ["奶油风", "原木风", "现代简约", "轻法式"];

/** 非确定性 GLB 的兜底配色；确定性商品模型使用自身 PBR 材质。 */
export const STYLE_PALETTES: Record<StyleName, Record<string, string>> = {
  奶油风: {
    沙发: "#E7D9C4", 茶几: "#CBB08A", 柜子: "#DECDB0", 床头柜: "#DECDB0",
    床: "#EADCC8", 餐桌: "#CBB08A", 餐椅: "#C7AD8C", 书桌: "#C9AD86",
    书椅: "#B29E82", 灯具: "#F2E6BE", 窗帘: "#EFE6D6", 地毯: "#CDC1A8",
  },
  原木风: {
    沙发: "#C69A6B", 茶几: "#8A6642", 柜子: "#A98557", 床头柜: "#A98557",
    床: "#B98F62", 餐桌: "#8A6642", 餐椅: "#96734C", 书桌: "#9C7A50",
    书椅: "#846A49", 灯具: "#E3C88F", 窗帘: "#D9C6A5", 地毯: "#A08A63",
  },
  现代简约: {
    沙发: "#C7C9CC", 茶几: "#9A9DA1", 柜子: "#B8BCC0", 床头柜: "#B8BCC0",
    床: "#C2C5C8", 餐桌: "#9A9DA1", 餐椅: "#8E9195", 书桌: "#A5A8AC",
    书椅: "#7F8387", 灯具: "#E0E2E4", 窗帘: "#D6D8DA", 地毯: "#A8ABAF",
  },
  轻法式: {
    沙发: "#E3CDD0", 茶几: "#C2A3A8", 柜子: "#D6C0C4", 床头柜: "#D6C0C4",
    床: "#E7D5D8", 餐桌: "#C2A3A8", 餐椅: "#B7949B", 书桌: "#C9ACB1",
    书椅: "#A98B91", 灯具: "#F0DCC8", 窗帘: "#EAD8DC", 地毯: "#C4ADB2",
  },
};

function makeItem(
  instanceId: string,
  sku: string,
  category: string,
  dimensions: [number, number, number],
  position: [number, number, number],
  rotationY = 0,
): SceneItem {
  return {
    instanceId,
    sku,
    category,
    dimensions: { x: dimensions[0], y: dimensions[1], z: dimensions[2] },
    transform: {
      position: { x: position[0], y: position[1], z: position[2] },
      rotation: { x: 0, y: rotationY, z: 0 },
      scale: { x: 1, y: 1, z: 1 },
    },
  };
}

function makeRoom(
  id: string,
  name: string,
  width: number,
  depth: number,
): SceneDocument["room"] {
  const halfWidth = width / 2;
  const halfDepth = depth / 2;
  return {
    id,
    name,
    floorPolygon: [
      { x: -halfWidth, z: -halfDepth },
      { x: halfWidth, z: -halfDepth },
      { x: halfWidth, z: halfDepth },
      { x: -halfWidth, z: halfDepth },
    ],
    ceilingHeight: 2.8,
    wallThickness: 0.12,
  };
}

function makeCamera(width: number, depth: number): SceneDocument["camera"] {
  return {
    position: { x: width * 1.15, y: 4.2, z: depth * 1.15 },
    target: { x: 0, y: 0.5, z: 0 },
    fov: 45,
  };
}

/** 三个空间的首页布局模板；SKU 均来自当前 40 件商品库。 */
export const HERO_DEMO_SCENES: Record<SpaceName, SceneDocument> = {
  客厅: {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: makeRoom("room-hero-living", "客厅", 4.6, 5.6),
    openings: [],
    items: [
      makeItem("item-sofa-1", "SF-001", "沙发", [2.38, 0.76, 0.98], [0, 0, -2.1]),
      makeItem("item-table-1", "CJ-001", "茶几", [1.2, 0.36, 0.6], [0, 0, -0.95]),
      makeItem("item-cab-1", "SJ-001", "柜子", [0.9, 1.8, 0.32], [-1.48, 0, -2.48]),
      makeItem("item-rug-1", "DT-001", "地毯", [2.0, 0.012, 2.9], [0, 0, -1.0]),
      makeItem("item-lamp-1", "DG-001", "灯具", [0.42, 1.52, 0.42], [-2.12, 0, -1.82]),
    ],
    camera: makeCamera(4.6, 5.6),
  },
  卧室: {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: makeRoom("room-hero-bedroom", "卧室", 3.6, 4.2),
    openings: [],
    items: [
      makeItem("item-bed-1", "CH-002", "床", [1.92, 1.08, 2.2], [0, 0, -0.65]),
      makeItem("item-night-1", "CT-001", "床头柜", [0.45, 0.52, 0.4], [-1.22, 0, -1.42]),
      makeItem("item-night-2", "CT-001", "床头柜", [0.45, 0.52, 0.4], [1.22, 0, -1.42]),
      makeItem("item-curtain-1", "CL-001", "窗帘", [2.8, 2.55, 0.11], [0, 0, -2.02]),
      makeItem("item-lamp-2", "DG-002", "灯具", [0.72, 1.52, 0.3], [0, 0, -1.35]),
    ],
    camera: makeCamera(3.6, 4.2),
  },
  餐厅: {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: makeRoom("room-hero-dining", "餐厅", 3.6, 3.8),
    openings: [],
    items: [
      makeItem("item-table-2", "ZY-001", "餐桌", [1.35, 0.75, 1.35], [0, 0, 0]),
      makeItem("item-chair-1", "CY-001", "餐椅", [0.5, 0.82, 0.55], [0, 0, -1.08]),
      makeItem("item-chair-2", "CY-001", "餐椅", [0.5, 0.82, 0.55], [0, 0, 1.08], Math.PI),
      makeItem("item-chair-3", "CY-001", "餐椅", [0.5, 0.82, 0.55], [-1.08, 0, 0], Math.PI / 2),
      makeItem("item-chair-4", "CY-001", "餐椅", [0.5, 0.82, 0.55], [1.08, 0, 0], -Math.PI / 2),
      makeItem("item-lamp-3", "DG-003", "灯具", [0.82, 1.65, 0.82], [0, 0, 0]),
    ],
    camera: makeCamera(3.6, 3.8),
  },
};

const HERO_STYLE_SKUS: Record<SpaceName, Record<StyleName, Record<string, string>>> = {
  客厅: {
    奶油风: { "item-sofa-1": "SF-001", "item-table-1": "CJ-001", "item-rug-1": "DT-001" },
    原木风: { "item-sofa-1": "HAUS-SOFA-006", "item-table-1": "HAUS-COFFEE-003", "item-rug-1": "DT-002" },
    现代简约: { "item-sofa-1": "HAUS-SOFA-003", "item-table-1": "HAUS-COFFEE-005", "item-rug-1": "DT-001" },
    轻法式: { "item-sofa-1": "HAUS-SOFA-005", "item-table-1": "HAUS-COFFEE-004", "item-rug-1": "DT-002" },
  },
  卧室: {
    奶油风: { "item-bed-1": "CH-002" },
    原木风: { "item-bed-1": "CH-001" },
    现代简约: { "item-bed-1": "HAUS-BED-007" },
    轻法式: { "item-bed-1": "HAUS-BED-005" },
  },
  餐厅: {
    奶油风: { "item-table-2": "ZY-001", "item-chair-1": "CY-001", "item-chair-2": "CY-001", "item-chair-3": "CY-001", "item-chair-4": "CY-001" },
    原木风: { "item-table-2": "ZY-002", "item-chair-1": "HAUS-CHAIR-004", "item-chair-2": "HAUS-CHAIR-004", "item-chair-3": "HAUS-CHAIR-004", "item-chair-4": "HAUS-CHAIR-004" },
    现代简约: { "item-table-2": "HAUS-DINING-006", "item-chair-1": "HAUS-CHAIR-007", "item-chair-2": "HAUS-CHAIR-007", "item-chair-3": "HAUS-CHAIR-007", "item-chair-4": "HAUS-CHAIR-007" },
    轻法式: { "item-table-2": "HAUS-DINING-004", "item-chair-1": "HAUS-CHAIR-005", "item-chair-2": "HAUS-CHAIR-005", "item-chair-3": "HAUS-CHAIR-005", "item-chair-4": "HAUS-CHAIR-005" },
  },
};

export function heroSceneFor(space: SpaceName, style: StyleName): SceneDocument {
  const base = HERO_DEMO_SCENES[space];
  const replacements = HERO_STYLE_SKUS[space][style];
  return {
    ...base,
    room: {
      ...base.room,
      floorPolygon: base.room.floorPolygon.map((point) => ({ ...point })),
    },
    items: base.items.map((item) => ({
      ...item,
      sku: replacements[item.instanceId] ?? item.sku,
      transform: {
        ...item.transform,
        position: { ...item.transform.position },
        rotation: { ...item.transform.rotation },
        scale: { ...item.transform.scale },
      },
    })),
  };
}

function hasReadyRule(product: FurnitureItem): boolean {
  const rule = product.modelSpecJson?.确定性建模规则 as
    | { 规则状态?: unknown }
    | undefined;
  return rule?.规则状态 === "ready";
}

export function heroProductMap(
  scene: SceneDocument,
  catalog: FurnitureItem[],
): Record<string, FurnitureItem | undefined> {
  const bySku = new Map(catalog.map((product) => [product.sku, product]));
  return Object.fromEntries(
    scene.items.map((item) => {
      const product = bySku.get(item.sku);
      return [item.instanceId, product && hasReadyRule(product) ? product : undefined];
    }),
  );
}

export function heroModelBaseY(product: FurnitureItem, ceilingHeight: number): number {
  if (product.modelSpecJson?.安装参数?.锚点 !== "ceiling") return 0;
  const rule = product.modelSpecJson.确定性建模规则 as
    | { 包围尺寸_mm?: { 高?: number } }
    | undefined;
  const modelHeight = (rule?.包围尺寸_mm?.高 ?? 0) / 1000;
  return Math.max(0, ceilingHeight - modelHeight);
}

/** 每件家具的 AI 点评（按类别），点击家具时展示。 */
export const FURNITURE_TIPS: Record<string, string> = {
  沙发: "这款 2.2 米沙发靠墙摆放，给客厅留出完整回游动线，坐深 95cm 适合窝着追剧。",
  茶几: "茶几与沙发保持约 45cm 间距，起身拿杯子、放遥控器都不费劲。",
  柜子: "柜体正对主要视线居中摆放，取物顺手，也压住空间重心。",
  床: "1.8 米大床靠后墙居中，两侧留出对称过道，起夜不绕路。",
  床头柜: "床头柜贴床两侧，睡前放手机、水杯触手可及。",
  餐桌: "餐桌居中摆放，四周留出 90cm 以上的回旋空间，多人聚餐不挤。",
  餐椅: "餐椅围绕餐桌四边、面向餐桌，入座动线最短。",
  灯具: "落地灯放在角落补光，晚上开一盏，氛围感就有了。",
  地毯: "地毯把会客区圈起来，视觉上划分空间，踩上去也更软。",
};
