import type { Furniture3DSpec } from "@/types/furniture";

export interface OpenGeometryMaterial {
  id: string;
  name: string;
  base_color: string;
  roughness: number;
  metallic: number;
}

export interface OpenGeometryDesign {
  schema_version: "furniture-open-geometry/1.0";
  name: string;
  description: string;
  scale: [number, number, number];
  materials: OpenGeometryMaterial[];
  parts: Array<{ id: string; name: string; material_id: string }>;
}

export interface OpenGeometryVersion {
  version: number;
  source: "llm" | "restore";
  instruction: string;
  design: OpenGeometryDesign;
  model_spec: Furniture3DSpec;
}

export interface OpenGeometryState {
  task_id: number;
  current_version: number;
  current: OpenGeometryVersion | null;
  history: OpenGeometryVersion[];
}

export interface OpenGeometryCommandResult extends OpenGeometryState {
  reply: string;
}

export function emptyOpenGeometryState(taskId: number): OpenGeometryState {
  return {
    task_id: taskId,
    current_version: 0,
    current: null,
    history: [],
  };
}
