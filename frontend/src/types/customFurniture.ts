import type { Furniture3DSpec } from "@/types/furniture";

export type CustomFurnitureFamily = "cabinet" | "table";
export type CabinetPurpose =
  | "wardrobe"
  | "entryway_cabinet"
  | "bookcase"
  | "balcony_storage";
export type TablePurpose = "dining_table" | "desk" | "kitchen_island";
export type CustomFurniturePurpose = CabinetPurpose | TablePurpose;
export type CabinetMaterial =
  | "E0 颗粒板"
  | "多层实木"
  | "实木（橡木）"
  | "E0 颗粒板（防潮封边）";
export type TableMaterial =
  | "实木（橡木）"
  | "岩板 + 金属"
  | "多层实木 + 岩板台面";
export type CustomFurnitureMaterial = CabinetMaterial | TableMaterial;

export interface CustomFurnitureDimensions {
  width_mm: number;
  height_mm: number;
  depth_mm: number;
}

export interface CabinetStructure {
  door_style: "hinged" | "sliding" | "open";
  door_count: number;
  compartment_count: number;
  shelf_count: number;
  drawer_count: number;
  panel_thickness_mm: number;
  leg_height_mm: number;
}

export interface TableStructure {
  top_shape: "rectangle" | "round";
  base_style: "four_leg" | "pedestal" | "trestle";
  support_count: number;
  seat_count: number;
  top_thickness_mm: number;
  edge_radius_mm: number;
}

export interface CabinetCustomFurnitureSpec {
  family: "cabinet";
  name: string;
  purpose: CabinetPurpose;
  material: CabinetMaterial;
  dimensions: CustomFurnitureDimensions;
  structure: CabinetStructure;
}

export interface TableCustomFurnitureSpec {
  family: "table";
  name: string;
  purpose: TablePurpose;
  material: TableMaterial;
  dimensions: CustomFurnitureDimensions;
  structure: TableStructure;
}

export type CustomFurnitureSpec =
  | CabinetCustomFurnitureSpec
  | TableCustomFurnitureSpec;

export interface CustomFurnitureSpecPatch {
  family?: CustomFurnitureFamily;
  name?: string;
  purpose?: CustomFurniturePurpose;
  material?: CustomFurnitureMaterial;
  dimensions?: Partial<CustomFurnitureDimensions>;
  structure?: Partial<CabinetStructure & TableStructure>;
}

export type QuoteReasonCode =
  | "quote_rule_missing"
  | "quote_rule_ambiguous"
  | "quote_rule_invalid";

export interface CustomFurnitureQuotePreview {
  status: "estimated" | "needs_human";
  reason_code: QuoteReasonCode | null;
  rule_id: number | null;
  project_name: string;
  material_grade: string;
  pricing_unit: string | null;
  unit_price: number | null;
  quantity: string | null;
  estimated_amount: string | null;
  currency: "CNY";
  description: string | null;
}

export interface CustomFurniturePreviewResult {
  status: "preview_ready" | "needs_human";
  spec: CustomFurnitureSpec;
  model_spec: Furniture3DSpec;
  quote_preview: CustomFurnitureQuotePreview;
  warnings: string[];
}
