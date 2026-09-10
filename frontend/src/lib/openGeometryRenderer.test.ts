import { describe, expect, it } from "vitest";
import { deterministicFurnitureRule, resolveFurnitureRenderer } from "@/lib/deterministicFurniture";
import type { Furniture3DSpec } from "@/types/furniture";
import {
  buildOpenGeometryPlacementRequest,
  openGeometryDefaultPlacement,
  openGeometryRoomCenterOffset,
  resolveOpenGeometryPlacementRefresh,
  roomItemRendererKind,
} from "@/lib/openGeometryScene";
import type { DesignScene, SceneItem } from "@/types/scene";


describe("开放几何确定性渲染契约", () => {
  it("识别 open_geometry_v1 并保留 sweep 参数与全局缩放", () => {
    const spec = {
      家具类型: "开放几何家具",
      确定性建模规则: {
        规则版本: "furniture-open-geometry/1.0",
        规则状态: "ready",
        模型ID: "OPEN-1",
        生成器: "open_geometry_v1",
        包围尺寸_mm: { 宽: 1000, 高: 800, 深: 600 },
        全局缩放: [1.1, 1, 1],
        外观规则: { 表面: { frame: "metal" } },
        材质槽: [{ 槽位ID: "frame", 材质: "框架", 表面类型: "metal", base_color: "#334433", roughness: 0.4, metallic: 0.7 }],
        部件: [{ 部件ID: "arc", 几何: "sweep", 尺寸_mm: [1000, 800, 600], 位置_mm: [0, 0, 0], 旋转_deg: [0, 0, 0], 材质槽: "frame", 几何参数: { path_mm: [[-500, 30, 0], [0, 700, -250], [500, 30, 0]], radius_mm: 30, tubular_segments: 24, radial_segments: 8, closed: false } }],
      },
    } as Furniture3DSpec;

    expect(resolveFurnitureRenderer(spec)).toEqual({ kind: "deterministic", generator: "open_geometry_v1" });
    expect(deterministicFurnitureRule(spec)?.部件[0].几何参数?.path_mm).toHaveLength(3);
    expect(deterministicFurnitureRule(spec)?.全局缩放).toEqual([1.1, 1, 1]);
  });

  it("按冻结快照中心把毫米精确换算为房间米制偏移", () => {
    const spec = {
      家具类型: "开放几何家具",
      确定性建模规则: {
        预览规则: { 中心_mm: [200, 500, -120], 半径_mm: 800 },
      },
    } as Furniture3DSpec;
    const item = {
      sourceType: "open_geometry_draft",
      openGeometryModelSpec: spec,
    } as SceneItem;

    expect(roomItemRendererKind(item)).toBe("open_geometry");
    expect(openGeometryRoomCenterOffset(spec)).toEqual([-0.2, -0.5, 0.12]);
  });

  it("只根据当前权威场景计算首次加入房间的中心落点", () => {
    const authoritativeScene = {
      id: 9,
      plan_version_id: 17,
      current_version: 3,
      scene: {
        schemaVersion: "1.0",
        unit: "m",
        coordinateSystem: "right-handed-y-up",
        room: {
          id: "room-1",
          name: "客厅",
          floorPolygon: [
            { x: 1, z: 2 },
            { x: 7, z: 2 },
            { x: 7, z: 6 },
            { x: 1, z: 6 },
          ],
          ceilingHeight: 2.8,
          wallThickness: 0.12,
        },
        openings: [],
        items: [],
      },
      validation: { valid: true, errors: [], warnings: [] },
      source: "manual",
    } satisfies DesignScene;

    const defaultPlacement = openGeometryDefaultPlacement(
      authoritativeScene,
      { scene_id: 9, version: 3 },
    );
    expect(defaultPlacement).toEqual({ x: 4, z: 4 });
    expect(buildOpenGeometryPlacementRequest({
      sceneReference: { scene_id: 9, version: 3 },
      clientMutationId: "open-place-center-001",
      openGeometryVersion: 6,
      position: defaultPlacement!,
    })).toEqual({
      baseVersion: 3,
      clientMutationId: "open-place-center-001",
      openGeometryVersion: 6,
      position: { x: 4, z: 4 },
      rotationY: 0,
    });
    expect(openGeometryDefaultPlacement(
      authoritativeScene,
      { scene_id: 9, version: 2 },
    )).toBeNull();
    expect(resolveOpenGeometryPlacementRefresh(
      { x: 1.5, z: 2.5 },
      { x: 4, z: 4 },
      true,
    )).toEqual({ x: 1.5, z: 2.5 });
  });
});
