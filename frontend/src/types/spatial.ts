/** 任务级整屋事实；所有房间共用米制 XZ 坐标，不应用单房间居中或缩放。 */
export interface SpatialPoint {
  x: number;
  z: number;
}

export interface SpatialRoom {
  id: string;
  name: string;
  polygon: SpatialPoint[];
  height: number;
}

export interface SpatialWall {
  id: string;
  start: SpatialPoint;
  end: SpatialPoint;
  room_ids: string[];
  height: number;
  thickness: number;
}

export interface SpatialOpening {
  id: string;
  wall_id: string;
  type: "door" | "window" | "passage";
  offset: number;
  width: number;
  height: number;
  sill_height: number;
}

export interface SpatialDocument {
  schema_version: "spatial/1.0";
  unit: "m";
  scale_status: "unconfirmed" | "confirmed";
  source_image_id: number | null;
  rooms: SpatialRoom[];
  walls: SpatialWall[];
  openings: SpatialOpening[];
}

export interface SpatialSaveRequest {
  base_version: number;
  client_mutation_id: string;
  document: SpatialDocument;
}

export interface SpatialResponse {
  task_id: number;
  version: number;
  document: SpatialDocument | null;
}
