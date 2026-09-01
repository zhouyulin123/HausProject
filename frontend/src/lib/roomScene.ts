import type { RoomModel } from "@/types/roomModel";
import type {
  SceneDocument,
  SceneOpening,
  ScenePoint,
  SceneVector3,
} from "@/types/scene";

export type RoomCameraPreset = "perspective" | "top" | "inside";

export interface RoomBounds {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  width: number;
  depth: number;
  centerX: number;
  centerZ: number;
}

export interface WallOpeningVisual extends SceneOpening {
  localX: number;
  worldPosition: SceneVector3;
}

export interface WallVisual {
  id: string;
  wallIndex: number;
  start: ScenePoint;
  end: ScenePoint;
  length: number;
  position: SceneVector3;
  rotationY: number;
  openings: WallOpeningVisual[];
}

export interface RoomCameraPose {
  position: SceneVector3;
  target: SceneVector3;
  up: SceneVector3;
}

export interface RoomFactSummary {
  dimensionsLabel: string;
  scaleLabel: string;
  confidenceLabel: string;
  openingCount: number;
  fixedObstacleCount: number;
  pendingConfirmationCount: number;
  obstacleNames: string[];
}

export function getRoomBounds(scene: SceneDocument): RoomBounds {
  const xs = scene.room.floorPolygon.map((point) => point.x);
  const zs = scene.room.floorPolygon.map((point) => point.z);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);

  return {
    minX,
    maxX,
    minZ,
    maxZ,
    width: maxX - minX,
    depth: maxZ - minZ,
    centerX: (minX + maxX) / 2,
    centerZ: (minZ + maxZ) / 2,
  };
}

function isRenderableOpening(
  opening: SceneOpening,
  wallLength: number,
  ceilingHeight: number,
): boolean {
  return (
    opening.offset >= 0 &&
    opening.width > 0 &&
    opening.offset + opening.width <= wallLength + 1e-6 &&
    opening.sillHeight >= 0 &&
    opening.height > 0 &&
    opening.sillHeight + opening.height <= ceilingHeight + 1e-6
  );
}

export function buildWallVisuals(scene: SceneDocument): WallVisual[] {
  const points = scene.room.floorPolygon;
  return points.map((start, wallIndex) => {
    const end = points[(wallIndex + 1) % points.length];
    const deltaX = end.x - start.x;
    const deltaZ = end.z - start.z;
    const length = Math.hypot(deltaX, deltaZ);
    const openings = scene.openings
      .filter(
        (opening) =>
          opening.wallIndex === wallIndex &&
          isRenderableOpening(
            opening,
            length,
            scene.room.ceilingHeight,
          ),
      )
      .map((opening) => {
        const centerDistance = opening.offset + opening.width / 2;
        const progress = length > 0 ? centerDistance / length : 0;
        return {
          ...opening,
          localX: -length / 2 + centerDistance,
          worldPosition: {
            x: start.x + deltaX * progress,
            y: opening.sillHeight + opening.height / 2,
            z: start.z + deltaZ * progress,
          },
        };
      });

    return {
      id: `wall-${wallIndex}`,
      wallIndex,
      start,
      end,
      length,
      position: {
        x: (start.x + end.x) / 2,
        y: scene.room.ceilingHeight / 2,
        z: (start.z + end.z) / 2,
      },
      rotationY: -Math.atan2(deltaZ, deltaX),
      openings,
    };
  });
}

export function getRoomCameraPose(
  scene: SceneDocument,
  preset: RoomCameraPreset,
): RoomCameraPose {
  const bounds = getRoomBounds(scene);
  const span = Math.max(bounds.width, bounds.depth, 1);
  const target = {
    x: bounds.centerX,
    y: Math.min(1, scene.room.ceilingHeight * 0.4),
    z: bounds.centerZ,
  };

  if (preset === "top") {
    return {
      position: {
        x: bounds.centerX,
        y: Math.max(scene.room.ceilingHeight * 2.4, span * 1.35),
        z: bounds.centerZ + 0.001,
      },
      target: { ...target, y: 0 },
      up: { x: 0, y: 0, z: -1 },
    };
  }

  if (preset === "inside") {
    return {
      position: {
        x: bounds.minX + Math.max(0.35, bounds.width * 0.12),
        y: Math.min(1.6, scene.room.ceilingHeight - 0.2),
        z: bounds.maxZ - Math.max(0.35, bounds.depth * 0.12),
      },
      target: { ...target, y: Math.min(1.25, scene.room.ceilingHeight * 0.45) },
      up: { x: 0, y: 1, z: 0 },
    };
  }

  return {
    position: {
      x: bounds.centerX + span * 0.95,
      y: Math.max(scene.room.ceilingHeight * 1.7, span * 0.72),
      z: bounds.centerZ + span * 1.1,
    },
    target,
    up: { x: 0, y: 1, z: 0 },
  };
}

function findMatchingRoom(scene: SceneDocument, roomModel: RoomModel) {
  return (
    roomModel.rooms.find((room) => room.id === scene.room.id) ??
    roomModel.rooms.find(
      (room) =>
        room.name.includes(scene.room.name) ||
        scene.room.name.includes(room.name),
    )
  );
}

export function buildRoomFactSummary(
  scene: SceneDocument,
  roomModel?: RoomModel | null,
): RoomFactSummary {
  const bounds = getRoomBounds(scene);
  const room = roomModel ? findMatchingRoom(scene, roomModel) : undefined;
  const obstacles = roomModel
    ? roomModel.fixedObstacles.filter(
        (obstacle) => !room || obstacle.roomId === room.id,
      )
    : [];
  const scaleLabels = {
    user: "用户已校准",
    vl: "AI 尺度估算",
    default: "默认尺寸",
  } as const;

  return {
    dimensionsLabel: `${bounds.width.toFixed(2)} × ${bounds.depth.toFixed(2)} × ${scene.room.ceilingHeight.toFixed(2)} m`,
    scaleLabel: roomModel ? scaleLabels[roomModel.scale.source] : "默认尺寸",
    confidenceLabel: roomModel
      ? `${Math.round(roomModel.confidence * 100)}%`
      : "未识别",
    openingCount: scene.openings.length,
    fixedObstacleCount: obstacles.length,
    pendingConfirmationCount: roomModel?.requiresConfirmation.length ?? 0,
    obstacleNames: obstacles.map((obstacle) => obstacle.name),
  };
}
