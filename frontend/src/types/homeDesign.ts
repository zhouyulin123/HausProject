export interface HomeMaterial {
  name: string;
  color: string;
}
export interface HomeQuoteRequest { home_version: number; region: string; client_mutation_id: string }
export interface HomeQuote {
  id: number;
  task_id: number;
  home_version: number;
  snapshot: {
    schema_version: string; rule_version: string; home_version: number; space_version: number;
    delivery_digest: string; region: string; created_at: string; currency: string;
    lines: {entity_type: string; id: string; room_id: string; room_name: string; name: string; unit: string; quantity: number | null; unit_price: number | null; total_price: number | null; price_status: string; reasons: string[]; asset_digest: string | null; source_id: number | null; source_version: number | null; source_data_version?: string | null; rule_evidence?: Record<string, unknown> | null; rule_evidence_digest?: string | null}[];
    known_subtotal: number; pending_count: number; total_price: number | null; limitations: string[]; content_digest: string;
    validation: HomeValidation; scale_status: string;
  };
}
export interface HomeQuoteList { items: HomeQuote[]; next_before_id: number | null }
export interface HomeSpaceImpactRequest {
  document: HomeDesignDocument;
  target_space_version: number;
}
export interface HomeSpaceImpact {
  task_id: number;
  source_space_version: number;
  target_space_version: number;
  target_space: import("./spatial").SpatialDocument;
  candidate_document: HomeDesignDocument;
  changes: { entity_type: "room" | "wall" | "opening" | "space"; entity_id: string; change: "added" | "removed" | "modified" }[];
  reference_issues: { entity_type: "object" | "surface" | "point"; entity_id: string; code: string; message: string }[];
  validation: HomeValidation | null;
  can_apply: boolean;
}
export interface HomeAgentRequest {
  client_turn_id: string;
  base_version: number;
  space_version: number;
  message: string;
  region: string | null;
  budget_max: number | null;
  allowed_asset_ids: number[];
}
export interface HomeAgentEvidence {
  schema_version: "home-agent-evidence/1.0";
  asset_refs: {
    asset_id: number;
    content_digest: string;
    source_id: number;
    source_version: number;
  }[];
  rule_version: "catalog-eligibility/home-agent-budget/1.0";
}
export interface HomeAgentBudgetPreview {
  region: string | null;
  currency: "CNY";
  known_subtotal: number;
  pending_count: number;
  total_price: number | null;
  budget_max: number | null;
  budget_status: "unknown" | "incomplete" | "within" | "over";
  limitations: string[];
}
export interface HomeAgentResponse {
  turn_id: number;
  outcome: "proposal" | "clarify" | "unsupported" | "invalid";
  message: string;
  candidate_document: HomeDesignDocument | null;
  validation: HomeValidation | null;
  base_version: number;
  space_version: number;
  evidence: HomeAgentEvidence;
  budget_preview: HomeAgentBudgetPreview;
}
export interface HomeAgentHistory {
  task_id: number;
  turns: {
    turn_id: number;
    client_turn_id: string;
    message: string;
    base_version: number;
    space_version: number;
    status: "running" | "completed" | "failed";
    response: HomeAgentResponse | null;
    error_code: string | null;
    created_at: string;
  }[];
  next_before_id: number | null;
}
export interface HomeSurface {
  id: string;
  room_id: string;
  kind: "floor" | "wall" | "ceiling";
  wall_id: string | null;
  quote_rule_id?: number;
  material: HomeMaterial;
}
export interface HomeObject {
  installation?: {kind: "floor" | "wall" | "ceiling"; wall_id: string | null} | null;
  clearance?: {front: number; back: number; left: number; right: number; above: number; confirmed: boolean} | null;
  point_requirement?: {point_id: string; max_distance_m: number} | null;
  id: string;
  asset_id?: number | null;
  room_id: string;
  name: string;
  category: "furniture" | "equipment" | "lighting" | "textile" | "fixture";
  position: { x: number; y: number; z: number };
  size: { width: number; height: number; depth: number };
  rotation: number;
  material: HomeMaterial;
}
export type HomeAssetKind = "product" | "open_geometry";
export interface HomeAssetOption {
  kind: HomeAssetKind;
  source_id: number;
  source_version: number | null;
  name: string;
  size: HomeObject["size"] | null;
  material: HomeMaterial | null;
  available: boolean;
  reason: string | null;
  source_summary?: Record<string, string | null>;
}
export interface HomeAssetRequest {
  client_mutation_id: string;
  kind: HomeAssetKind;
  source_id: number;
  source_version: number;
}
export interface HomeAsset {
  id: number;
  task_id: number;
  kind: HomeAssetKind;
  source_id: number;
  source_version: number;
  name: string;
  size: HomeObject["size"];
  material: HomeMaterial;
  model_spec: import("./furniture").Furniture3DSpec;
  content_digest: string;
  source_summary?: Record<string, string | null>;
}
export interface HomeAssetOptions {
  items: HomeAssetOption[];
  next_after_id: number | null;
}
export interface HomeDesignDocument {
  points?: HomePoint[];
  schema_version: "home-design/1.0";
  space_version: number;
  surfaces: HomeSurface[];
  objects: HomeObject[];
}
export interface HomePoint {
  id: string;
  name: string;
  room_id: string;
  kind: "socket" | "switch" | "water" | "drain" | "network" | "other";
  position: HomeObject["position"];
  confirmed: boolean;
}
export interface HomeValidation {
  valid: boolean;
  issues: {
    code: string;
    message: string;
    object_ids: string[];
    opening_id?: string | null;
  }[];
}
export interface HomeDesignResponse {
  task_id: number;
  version: number;
  document: HomeDesignDocument | null;
  validation?: HomeValidation | null;
}
export interface HomeSaveRequest {
  base_version: number;
  client_mutation_id: string;
  document: HomeDesignDocument;
}
export interface HomeVersionList {
  task_id: number;
  versions: {
    version: number;
    created_at: string;
    space_version: number;
    object_count: number;
    valid: boolean;
  }[];
  next_before_version: number | null;
}
export interface HomeDeliveryLine {
  asset?: Omit<HomeAsset, "model_spec"> | null;
  entity_type: "surface" | "object";
  id: string;
  room_id: string;
  room_name: string;
  name: string;
  material: HomeMaterial;
  unit: "m2" | "piece";
  quantity: number | null;
  quantity_status: string;
  unit_price: null;
  total_price: null;
  price_status: "pending_quote";
}
export interface HomeDelivery {
  schema_version: "home-delivery/1.0";
  task_id: number;
  home_version: number;
  space_version: number;
  purpose: "concept_review";
  document: HomeDesignDocument;
  space: import("./spatial").SpatialDocument;
  lines: HomeDeliveryLine[];
  validation: HomeValidation;
  gaps: { code: string; entity_type: string | null; id: string | null }[];
  limitations: string[];
  total_price: null;
  price_status: "pending_quote";
  content_digest: string;
}
export interface HomeComparison {
  schema_version: "home-comparison/1.0";
  task_id: number;
  from_version: number;
  to_version: number;
  from_space_version: number;
  to_space_version: number;
  space_changed: boolean;
  validation_changed: boolean;
  before_validation: HomeValidation;
  after_validation: HomeValidation;
  changes: {
    entity_type: "surface" | "object" | "point";
    id: string;
    change: "added" | "removed" | "modified";
    changed_fields: string[];
    before: HomeObject | HomeSurface | HomePoint | null;
    after: HomeObject | HomeSurface | HomePoint | null;
    before_line: HomeDeliveryLine | null;
    after_line: HomeDeliveryLine | null;
  }[];
  limitations: string[];
}
