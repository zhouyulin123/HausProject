import type { Furniture3DSpec } from "@/types/furniture";
import type { AgentSceneReference } from "@/types/agent";
import type { DesignScene, SceneItem, ScenePoint } from "@/types/scene";

export interface OpenGeometryPlacementRequest {
  baseVersion: number;
  clientMutationId: string;
  openGeometryVersion: number;
  position: ScenePoint;
  rotationY: number;
}

export function openGeometryDefaultPlacement(
  authoritativeScene: DesignScene | null | undefined,
  sceneReference: AgentSceneReference | null | undefined,
): ScenePoint | null {
  if (
    !authoritativeScene
    || !sceneReference
    || authoritativeScene.id !== sceneReference.scene_id
    || authoritativeScene.current_version !== sceneReference.version
  ) return null;
  const polygon = authoritativeScene.scene.room.floorPolygon;
  if (
    polygon.length < 3
    || polygon.some((point) => !Number.isFinite(point.x) || !Number.isFinite(point.z))
  ) return null;
  const sum = polygon.reduce(
    (current, point) => ({ x: current.x + point.x, z: current.z + point.z }),
    { x: 0, z: 0 },
  );
  return { x: sum.x / polygon.length, z: sum.z / polygon.length };
}

export function buildOpenGeometryPlacementRequest({
  sceneReference,
  clientMutationId,
  openGeometryVersion,
  position,
}: {
  sceneReference: AgentSceneReference;
  clientMutationId: string;
  openGeometryVersion: number;
  position: ScenePoint;
}): OpenGeometryPlacementRequest {
  return {
    baseVersion: sceneReference.version,
    clientMutationId,
    openGeometryVersion,
    position,
    rotationY: 0,
  };
}

export function resolveOpenGeometryPlacementRefresh(
  current: ScenePoint,
  nextDefault: ScenePoint | null,
  userEdited: boolean,
): ScenePoint {
  return !userEdited && nextDefault ? nextDefault : current;
}

export function roomItemRendererKind(
  item: SceneItem,
): "catalog" | "open_geometry" {
  return item.sourceType === "open_geometry_draft"
    && item.openGeometryModelSpec
    ? "open_geometry"
    : "catalog";
}

export function openGeometryRoomCenterOffset(
  spec: Furniture3DSpec,
): [number, number, number] {
  const rule = spec.确定性建模规则 as {
    预览规则?: { 中心_mm?: unknown };
  } | undefined;
  const center = rule?.预览规则?.中心_mm;
  if (
    !Array.isArray(center)
    || center.length !== 3
    || center.some((value) => typeof value !== "number" || !Number.isFinite(value))
  ) return [0, 0, 0];
  return center.map((value) => -value / 1000) as [number, number, number];
}
