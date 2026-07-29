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
  /** 以下字段由后端商品库回填（方案中的家具携带） */
  sku?: string;
  quantity?: number;
  unitPrice?: number;
  subtotal?: number;
}
