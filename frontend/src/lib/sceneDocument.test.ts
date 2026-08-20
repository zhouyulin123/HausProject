import { describe, expect, it } from "vitest";
import { mockDesigns } from "@/data/mockDesigns";
import type { RoomModel } from "@/types/roomModel";
import {
  buildSceneDocument,
  clampItemTransform,
  isDemoScene,
  updateSceneItemTransform,
} from "./sceneDocument";

function livingRoomModel(overrides: Partial<RoomModel> = {}): RoomModel {
  return {
    schemaVersion: "1.0",
    imageKind: "floor_plan",
    spaceType: "客厅",
    roomCount: "三室两厅",
    rooms: [
      {
        id: "living-room",
        name: "客厅",
        floorPolygon: [
          { x: 0, z: 0 },
          { x: 1, z: 0 },
          { x: 1, z: 1 },
          { x: 0, z: 1 },
        ],
        ceilingHeight: 3.0,
        widthM: 6.0,
        depthM: 7.0,
        confidence: 0.9,
      },
    ],
    walls: [],
    doors: [],
    windows: [],
    fixedObstacles: [],
    existingFurniture: [],
    scale: { source: "user", confidence: 1 },
    confidence: 0.9,
    requiresConfirmation: [],
    analysisNotes: [],
    suggestions: [],
    ...overrides,
  };
}

describe("方案到 3D 场景转换", () => {
  it("生成统一米制、Y 轴向上的场景文档", () => {
    const scene = buildSceneDocument(mockDesigns[0], "客厅");

    expect(scene.schemaVersion).toBe("1.0");
    expect(scene.unit).toBe("m");
    expect(scene.coordinateSystem).toBe("right-handed-y-up");
    expect(scene.room.floorPolygon).toHaveLength(4);
    expect(scene.items.length).toBeGreaterThan(0);
    expect(scene.items.every((item) => item.sku.length > 0)).toBe(true);
    expect(new Set(scene.items.map((item) => item.instanceId)).size).toBe(
      scene.items.length,
    );
  });

  it("更新家具变换时不修改原场景", () => {
    const scene = buildSceneDocument(mockDesigns[0], "客厅");
    const item = scene.items[0];

    const updated = updateSceneItemTransform(scene, item.instanceId, {
      ...item.transform,
      position: { ...item.transform.position, x: 1.2 },
    });

    expect(updated).not.toBe(scene);
    expect(updated.items[0]).not.toBe(item);
    expect(updated.items[0].transform.position.x).toBe(1.2);
    expect(scene.items[0].transform.position.x).not.toBe(1.2);
  });

  it("把家具完整占地限制在矩形房间边界内", () => {
    const scene = buildSceneDocument(mockDesigns[0], "客厅");
    const item = scene.items[0];

    const clamped = clampItemTransform(scene, item, {
      ...item.transform,
      position: { x: 99, y: -3, z: -99 },
    });

    const halfWidth = scene.room.floorPolygon[1].x;
    const halfDepth = scene.room.floorPolygon[2].z;
    expect(clamped.position.x).toBeLessThan(halfWidth);
    expect(clamped.position.z).toBeGreaterThan(-halfDepth);
    expect(clamped.position.y).toBe(item.dimensions!.y / 2);
  });

  it("明确识别仅供本地展示的 DEMO SKU", () => {
    const scene = buildSceneDocument(mockDesigns[0], "客厅");
    const productionScene = {
      ...scene,
      items: scene.items.map((item, index) => ({
        ...item,
        sku: `SKU-${index + 1}`,
      })),
    };

    expect(isDemoScene(scene)).toBe(true);
    expect(isDemoScene(productionScene)).toBe(false);
  });

  it("找不到家具实例时保持原场景引用", () => {
    const scene = buildSceneDocument(mockDesigns[0], "客厅");

    const unchanged = updateSceneItemTransform(
      scene,
      "missing-item",
      scene.items[0].transform,
    );

    expect(unchanged).toBe(scene);
  });

  it("RoomModel 提供校准尺寸时优先采用真实宽深与层高", () => {
    const scene = buildSceneDocument(mockDesigns[0], "客厅", livingRoomModel());

    const xs = scene.room.floorPolygon.map((p) => p.x);
    const zs = scene.room.floorPolygon.map((p) => p.z);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(6.0);
    expect(Math.max(...zs) - Math.min(...zs)).toBeCloseTo(7.0);
    expect(scene.room.ceilingHeight).toBe(3.0);
  });

  it("RoomModel 与房间类型不匹配时回退默认尺寸", () => {
    const roomModel = livingRoomModel({
      rooms: [{ ...livingRoomModel().rooms[0], name: "卧室" }],
    });

    const scene = buildSceneDocument(mockDesigns[0], "客厅", roomModel);

    const xs = scene.room.floorPolygon.map((p) => p.x);
    const zs = scene.room.floorPolygon.map((p) => p.z);
    expect(Math.max(...xs) - Math.min(...xs)).toBeCloseTo(4.6);
    expect(Math.max(...zs) - Math.min(...zs)).toBeCloseTo(5.6);
    expect(scene.room.ceilingHeight).toBe(2.8);
  });
});
