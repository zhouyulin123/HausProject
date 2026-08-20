/** Web 编辑器、Scene Agent 与 Blender 交换的 3D 场景契约。 */

export interface ScenePoint {
  x: number;
  z: number;
}

export interface SceneVector3 {
  x: number;
  y: number;
  z: number;
}

export interface SceneTransform {
  position: SceneVector3;
  /** 欧拉角，单位为弧度。 */
  rotation: SceneVector3;
  scale: SceneVector3;
}

export interface SceneRoom {
  id: string;
  name: string;
  floorPolygon: ScenePoint[];
  ceilingHeight: number;
  wallThickness: number;
}

export interface SceneOpening {
  id: string;
  type: "door" | "window" | "passage";
  wallIndex: number;
  offset: number;
  width: number;
  height: number;
  sillHeight: number;
}

export interface SceneMaterialOverride {
  slot: string;
  materialId?: string | null;
  color?: string | null;
}

export interface SceneItem {
  instanceId: string;
  /** 必须对应服务端商品库中的有效 SKU。 */
  sku: string;
  category?: string | null;
  transform: SceneTransform;
  dimensions?: SceneVector3 | null;
  materials?: SceneMaterialOverride[];
}

export interface SceneCamera {
  position: SceneVector3;
  target: SceneVector3;
  fov: number;
}

export interface SceneDocument {
  schemaVersion: "1.0";
  unit: "m";
  coordinateSystem: "right-handed-y-up";
  room: SceneRoom;
  openings: SceneOpening[];
  items: SceneItem[];
  camera?: SceneCamera | null;
}

export interface SceneValidationIssue {
  code: string;
  message: string;
  path?: string | null;
}

export interface SceneValidationReport {
  valid: boolean;
  errors: SceneValidationIssue[];
  warnings: SceneValidationIssue[];
}

export type SceneSource =
  | "manual"
  | "scene_agent"
  | "import"
  | "migration"
  | "auto_layout";

export interface DesignScene {
  id: number;
  plan_version_id: number;
  current_version: number;
  scene: SceneDocument;
  validation: SceneValidationReport;
  source: SceneSource;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DesignSceneVersion {
  version: number;
  scene: SceneDocument;
  validation: SceneValidationReport;
  source: SceneSource;
  created_at?: string | null;
}

export type SceneOperation =
  | {
      type: "move";
      instanceId: string;
      position: ScenePoint;
    }
  | {
      type: "rotate";
      instanceId: string;
      rotationY: number;
    }
  | {
      type: "remove";
      instanceId: string;
    }
  | {
      type: "add";
      sku: string;
      position: ScenePoint;
      rotationY: number;
    };

export interface SceneAgentCommandResult {
  message: string;
  operations: SceneOperation[];
  scene: DesignScene;
}

export type BlenderRenderProfile = "preview" | "final";
export type BlenderRenderStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed";

export interface BlenderRenderJob {
  id: number;
  scene_id: number;
  scene_version: number;
  profile: BlenderRenderProfile;
  status: BlenderRenderStatus;
  progress: number;
  attempt: number;
  output_url: string | null;
  error_message: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}
