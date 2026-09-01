import { describe, expect, it } from "vitest";
import type { RoomModel } from "@/types/roomModel";
import type { SceneDocument } from "@/types/scene";
import {
  buildRoomFactSummary,
  buildWallVisuals,
  getRoomBounds,
  getRoomCameraPose,
} from "./roomScene";

const scene: SceneDocument = {
  schemaVersion: "1.0",
  unit: "m",
  coordinateSystem: "right-handed-y-up",
  room: {
    id: "living-room",
    name: "客厅",
    floorPolygon: [
      { x: -3, z: -2 },
      { x: 3, z: -2 },
      { x: 3, z: 2 },
      { x: -3, z: 2 },
    ],
    ceilingHeight: 2.8,
    wallThickness: 0.12,
  },
  openings: [
    {
      id: "door-main",
      type: "door",
      wallIndex: 0,
      offset: 0.6,
      width: 0.9,
      height: 2.1,
      sillHeight: 0,
    },
    {
      id: "window-east",
      type: "window",
      wallIndex: 1,
      offset: 1,
      width: 1.6,
      height: 1.2,
      sillHeight: 0.9,
    },
  ],
  items: [],
};

const roomModel: RoomModel = {
  schemaVersion: "1.0",
  imageKind: "floor_plan",
  spaceType: "客厅",
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
      widthM: 6,
      depthM: 4,
      ceilingHeight: 2.8,
      confidence: 0.91,
    },
  ],
  walls: [],
  doors: [],
  windows: [],
  fixedObstacles: [
    { name: "承重柱", roomId: "living-room", confidence: 0.62 },
  ],
  existingFurniture: [],
  scale: { source: "user", confidence: 1 },
  confidence: 0.86,
  requiresConfirmation: ["windowWidth"],
  analysisNotes: [],
  suggestions: [],
};

describe("数字房间可视化数据", () => {
  it("为墙体生成洞口轮廓与米制尺寸", () => {
    const walls = buildWallVisuals(scene);

    expect(walls).toHaveLength(4);
    expect(walls[0].length).toBe(6);
    expect(walls[0].openings).toEqual([
      expect.objectContaining({
        id: "door-main",
        localX: -1.95,
        width: 0.9,
        height: 2.1,
      }),
    ]);
    expect(walls[1].openings[0]).toEqual(
      expect.objectContaining({ id: "window-east", sillHeight: 0.9 }),
    );
  });

  it("从任意多边形计算稳定包围盒和中心", () => {
    expect(getRoomBounds(scene)).toEqual({
      minX: -3,
      maxX: 3,
      minZ: -2,
      maxZ: 2,
      width: 6,
      depth: 4,
      centerX: 0,
      centerZ: 0,
    });
  });

  it("提供全景、俯视与室内三种不会落在地面下的相机视角", () => {
    for (const preset of ["perspective", "top", "inside"] as const) {
      const pose = getRoomCameraPose(scene, preset);
      expect(pose.position.y).toBeGreaterThan(0);
      expect(pose.target).toEqual(expect.objectContaining({ x: 0, z: 0 }));
    }
  });

  it("区分用户校准、待确认事实和无坐标固定障碍", () => {
    expect(buildRoomFactSummary(scene, roomModel)).toEqual(
      expect.objectContaining({
        dimensionsLabel: "6.00 × 4.00 × 2.80 m",
        scaleLabel: "用户已校准",
        confidenceLabel: "86%",
        openingCount: 2,
        fixedObstacleCount: 1,
        pendingConfirmationCount: 1,
        obstacleNames: ["承重柱"],
      }),
    );
  });

  it("VL 和默认尺度不会被标记为已校准", () => {
    expect(
      buildRoomFactSummary(scene, {
        ...roomModel,
        scale: { source: "vl", confidence: 0.58 },
      }).scaleLabel,
    ).toBe("AI 尺度估算");
    expect(buildRoomFactSummary(scene, null).scaleLabel).toBe("默认尺寸");
  });

  it("场景与 RoomModel 房间不匹配时不叠加其他房间障碍", () => {
    const summary = buildRoomFactSummary(
      {
        ...scene,
        room: { ...scene.room, id: "bedroom", name: "卧室" },
      },
      roomModel,
    );

    expect(summary.fixedObstacleCount).toBe(0);
    expect(summary.obstacleNames).toEqual([]);
  });
});
