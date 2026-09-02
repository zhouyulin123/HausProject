import type { DesignPlan } from "@/types/design";
import type {
  SceneDocument,
  SceneItem,
  SceneTransform,
} from "@/types/scene";
import type { RoomModel } from "@/types/roomModel";
import { computeRoomLayout } from "./roomLayout";

const DEMO_SKU_PREFIX = "DEMO-";
const OPENING_DEFAULTS = {
  door: { height: 2.1, sillHeight: 0 },
  passage: { height: 2.1, sillHeight: 0 },
  window: { height: 1.5, sillHeight: 0.9 },
} as const;

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
  const normalizedPoints = room?.floorPolygon ?? [];
  const normalizedXs = normalizedPoints.map((point) => point.x);
  const normalizedZs = normalizedPoints.map((point) => point.z);
  const minimumNormalizedX = Math.min(...normalizedXs);
  const maximumNormalizedX = Math.max(...normalizedXs);
  const minimumNormalizedZ = Math.min(...normalizedZs);
  const maximumNormalizedZ = Math.max(...normalizedZs);
  const normalizedWidth = maximumNormalizedX - minimumNormalizedX;
  const normalizedDepth = maximumNormalizedZ - minimumNormalizedZ;
  const hasValidRoomPolygon =
    normalizedPoints.length >= 3 &&
    Number.isFinite(normalizedWidth) &&
    Number.isFinite(normalizedDepth) &&
    normalizedWidth > 0 &&
    normalizedDepth > 0;
  const floorPolygon = hasValidRoomPolygon
    ? normalizedPoints.map((point) => ({
        x:
          ((point.x - minimumNormalizedX) / normalizedWidth - 0.5) *
          layout.width,
        z:
          ((point.z - minimumNormalizedZ) / normalizedDepth - 0.5) *
          layout.depth,
      }))
    : [
        { x: -halfWidth, z: -halfDepth },
        { x: halfWidth, z: -halfDepth },
        { x: halfWidth, z: halfDepth },
        { x: -halfWidth, z: halfDepth },
      ];
  const openings = room
    ? [...(roomModel?.doors ?? []), ...(roomModel?.windows ?? [])]
        .filter(
          (opening) =>
            opening.roomId === room.id &&
            opening.wallIndex >= 0 &&
            opening.wallIndex < floorPolygon.length,
        )
        .map((opening) => {
          const start = floorPolygon[opening.wallIndex];
          const end =
            floorPolygon[(opening.wallIndex + 1) % floorPolygon.length];
          const wallLength = Math.hypot(end.x - start.x, end.z - start.z);
          const defaults = OPENING_DEFAULTS[opening.type];
          return {
            id: opening.id,
            type: opening.type,
            wallIndex: opening.wallIndex,
            offset: opening.offset * wallLength,
            width: opening.width * wallLength,
            height: opening.height ?? defaults.height,
            sillHeight:
              opening.sillHeight > 0
                ? opening.sillHeight
                : defaults.sillHeight,
          };
        })
    : [];

  return {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: {
      id: room?.id ?? `room-${safeIdentifier(roomType)}`,
      name: room?.name ?? roomType,
      floorPolygon,
      ceilingHeight,
      wallThickness: 0.12,
    },
    openings,
    items: layout.items.map((layoutItem, index) => {
      const furniture = plan.furnitureSuggestions.find(
        (item) =>
          item.sku === layoutItem.id || item.id === layoutItem.id,
      );
      const sku =
        furniture?.sku ??
        `${DEMO_SKU_PREFIX}${safeIdentifier(furniture?.id ?? layoutItem.id)}`;
      const assetMode = furniture?.assetMode ?? "parametric";
      return {
        instanceId: `item-${safeIdentifier(sku)}-${index + 1}`,
        sku,
        category: layoutItem.category,
        assetMode,
        fallbackReason:
          furniture?.fallbackReason ??
          (furniture?.assetMode ? null : "asset_contract_missing"),
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
