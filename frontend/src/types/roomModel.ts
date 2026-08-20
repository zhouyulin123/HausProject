/** RoomModel：VL 空间识别产出的统一空间事实模型（与后端 camelCase 序列化对齐）。 */

export interface RoomModelPoint {
  x: number;
  z: number;
}

export interface RoomModelPolygon {
  id: string;
  name: string;
  floorPolygon: RoomModelPoint[];
  ceilingHeight?: number | null;
  /** 用户校准后的真实宽/深（米） */
  widthM?: number | null;
  depthM?: number | null;
  confidence: number;
}

export interface RoomModelOpening {
  id: string;
  roomId: string;
  type: "door" | "window" | "passage";
  wallIndex: number;
  offset: number;
  width: number;
  height?: number | null;
  sillHeight: number;
  confidence: number;
}

export interface RoomModelWall {
  roomId: string;
  wallIndex: number;
  loadBearing?: boolean | null;
  confidence: number;
}

export interface RoomModelFurniture {
  name: string;
  category: string;
  roomId: string;
  confidence: number;
}

export interface RoomModelObstacle {
  name: string;
  roomId: string;
  confidence: number;
}

export interface RoomModelScale {
  source: "vl" | "user" | "default";
  referenceWallLength?: number | null;
  referenceRoomId?: string | null;
  referenceWallIndex?: number | null;
  confidence: number;
}

export interface RoomModel {
  schemaVersion: "1.0";
  imageKind?: "floor_plan" | "room_photo" | "other" | null;
  spaceType?: string | null;
  roomCount?: string | null;
  rooms: RoomModelPolygon[];
  walls: RoomModelWall[];
  doors: RoomModelOpening[];
  windows: RoomModelOpening[];
  fixedObstacles: RoomModelObstacle[];
  existingFurniture: RoomModelFurniture[];
  scale: RoomModelScale;
  confidence: number;
  requiresConfirmation: string[];
  analysisNotes: string[];
  suggestions: string[];
}
