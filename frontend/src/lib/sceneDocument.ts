import type { DesignPlan } from "@/types/design";
import type {
  SceneDocument,
  SceneItem,
  SceneTransform,
} from "@/types/scene";
import type { RoomModel } from "@/types/roomModel";
import { computeRoomLayout } from "./roomLayout";

const DEMO_SKU_PREFIX = "DEMO-";

function safeIdentifier(value: string): string {
  const normalized = value.replace(/[^A-Za-z0-9._-]+/g, "-");
  return normalized.replace(/^-+|-+$/g, "") || "item";
}

/**
 * 把确定性规则布局转换成服务端、Web 编辑器和 Blender 共用的场景文档。
 * 没有真实 SKU 的本地 Mock 使用 DEMO 前缀，只用于预览，不提交服务端。
 * roomModel 提供 VL 识别 + 用户校准后的真实空间尺寸时，优先采用它替换默认尺寸。
 */
export function buildSceneDocument(
  plan: DesignPlan,
  roomType: string,
  roomModel?: RoomModel | null,
): SceneDocument {
  const room = roomModel?.rooms.find(
    (candidate) =>
      candidate.name.includes(roomType) || roomType.includes(candidate.name),
  );
  const size =
    room && room.widthM && room.depthM
      ? { width: room.widthM, depth: room.depthM }
      : undefined;
  const layout = computeRoomLayout(plan, roomType, size);
  const halfWidth = layout.width / 2;
  const halfDepth = layout.depth / 2;
  const ceilingHeight = room?.ceilingHeight ?? layout.height;

  return {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: {
      id: `room-${safeIdentifier(roomType)}`,
      name: roomType,
      floorPolygon: [
        { x: -halfWidth, z: -halfDepth },
        { x: halfWidth, z: -halfDepth },
        { x: halfWidth, z: halfDepth },
        { x: -halfWidth, z: halfDepth },
      ],
      ceilingHeight,
      wallThickness: 0.12,
    },
    openings: [],
    items: layout.items.map((layoutItem, index) => {
      const furniture = plan.furnitureSuggestions.find(
        (item) =>
          item.sku === layoutItem.id || item.id === layoutItem.id,
      );
      const sku =
        furniture?.sku ??
        `${DEMO_SKU_PREFIX}${safeIdentifier(furniture?.id ?? layoutItem.id)}`;
      return {
        instanceId: `item-${safeIdentifier(sku)}-${index + 1}`,
        sku,
        category: layoutItem.category,
        dimensions: {
          x: layoutItem.size[0],
          y: layoutItem.size[1],
          z: layoutItem.size[2],
        },
        transform: {
          position: {
            x: layoutItem.position[0],
            y: layoutItem.position[1],
            z: layoutItem.position[2],
          },
          rotation: { x: 0, y: layoutItem.rotationY, z: 0 },
          scale: { x: 1, y: 1, z: 1 },
        },
        materials: [],
      };
    }),
    camera: {
      position: {
        x: layout.width * 1.15,
        y: ceilingHeight * 2.2,
        z: layout.depth * 1.35,
      },
      target: { x: 0, y: 0.5, z: 0 },
      fov: 45,
    },
  };
}

export function updateSceneItemTransform(
  scene: SceneDocument,
  instanceId: string,
  transform: SceneTransform,
): SceneDocument {
  const itemIndex = scene.items.findIndex(
    (item) => item.instanceId === instanceId,
  );
  if (itemIndex < 0) return scene;

  return {
    ...scene,
    items: scene.items.map((item, index) =>
      index === itemIndex ? { ...item, transform } : item,
    ),
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  if (minimum > maximum) return (minimum + maximum) / 2;
  return Math.min(maximum, Math.max(minimum, value));
}

/** 将家具完整占地限制在户型包围盒内；非矩形户型仍由服务端语义校验复核。 */
export function clampItemTransform(
  scene: SceneDocument,
  item: SceneItem,
  transform: SceneTransform,
): SceneTransform {
  const xs = scene.room.floorPolygon.map((point) => point.x);
  const zs = scene.room.floorPolygon.map((point) => point.z);
  const minimumX = Math.min(...xs);
  const maximumX = Math.max(...xs);
  const minimumZ = Math.min(...zs);
  const maximumZ = Math.max(...zs);
  const dimensions = item.dimensions ?? { x: 1, y: 0.8, z: 1 };
  const rotationY = transform.rotation.y;
  const cosine = Math.abs(Math.cos(rotationY));
  const sine = Math.abs(Math.sin(rotationY));
  const scaledWidth = dimensions.x * transform.scale.x;
  const scaledDepth = dimensions.z * transform.scale.z;
  const halfExtentX = (scaledWidth * cosine + scaledDepth * sine) / 2;
  const halfExtentZ = (scaledWidth * sine + scaledDepth * cosine) / 2;

  return {
    ...transform,
    position: {
      x: clamp(
        transform.position.x,
        minimumX + halfExtentX,
        maximumX - halfExtentX,
      ),
      y: (dimensions.y * transform.scale.y) / 2,
      z: clamp(
        transform.position.z,
        minimumZ + halfExtentZ,
        maximumZ - halfExtentZ,
      ),
    },
  };
}

export function isDemoScene(scene: SceneDocument): boolean {
  return scene.items.some((item) => item.sku.startsWith(DEMO_SKU_PREFIX));
}
