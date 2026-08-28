export interface FurnitureItem {
  id: string;
  name: string;
  /** 家具类型：沙发 / 茶几 / 柜子 / 灯具 等 */
  category: string;
  /** 适用空间：客厅 / 卧室 / 餐厅 / 书房 */
  room: string;
  style: string;
  material: string;
  priceRange: string;
  sizeSuggestion: string;
  /** AI 匹配指数 0-100 */
  matchScore: number;
  /** AI 推荐理由 */
  reason: string;
  /** 替代选择 */
  alternative: string;
  /** 占位图渐变（Tailwind class） */
  gradient: string;
  /** 真实产品图 URL（商品库有图时优先展示） */
  imageUrl?: string;
  /** 可加载的 glTF 2.0 二进制商品模型。 */
  modelUrl?: string;
  modelStatus?: "missing" | "ready" | "failed";
  modelDimensionsMm?: {
    width: number | null;
    height: number | null;
    depth: number | null;
  };
  /** 3D 建模真实参数（尺寸/结构/造型/材质PBR/工艺），用于程序化渲染。 */
  modelSpecJson?: Furniture3DSpec;
  /** 以下字段由后端商品库回填（方案中的家具携带） */
  sku?: string;
  quantity?: number;
  unitPrice?: number;
  subtotal?: number;
}

/** 单件家具 3D 建模材质参数（PBR）。 */
export interface FurnitureMaterialSpec {
  部位?: string;
  材质?: string;
  base_color?: string | string[];
  roughness?: number;
  metallic?: number;
  normal_strength?: number;
  [key: string]: unknown;
}

/** 单件家具的完整 3D 建模参数（对应 backend/furniture_3d_specs.json 的每一项）。 */
export interface Furniture3DSpec {
  家具类型?: string;
  家具名称?: string;
  风格?: string;
  空间?: string;
  匹配度?: number;
  参考价格_元?: number[];
  尺寸参数?: Record<string, number | number[]>;
  结构参数?: Record<string, unknown>;
  造型参数?: Record<string, unknown>;
  材质参数?: FurnitureMaterialSpec[];
  工艺细节?: Record<string, unknown>;
  真实制造约束?: Record<string, unknown>;
  网格与贴图?: Record<string, unknown>;
  图片生成提示词?: string;
  确定性建模规则?: Record<string, unknown>;
  /** 程序化模型的显式安装锚点，避免按名称猜测落地/吊装。 */
  安装参数?: {
    锚点: "floor" | "ceiling" | "wall";
    默认垂吊_mm?: number;
    灯具模型?: "floor" | "pendant" | "ring";
  };
}
