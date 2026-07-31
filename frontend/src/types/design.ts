import type { FurnitureItem } from "./furniture";

export interface ColorItem {
  name: string;
  hex: string;
  /** 颜色用途：墙面 / 柜体 / 沙发 / 窗帘 / 点缀色 */
  usage: string;
}

export interface MaterialItem {
  name: string;
  description: string;
  gradient: string;
}

export interface BudgetItem {
  name: string;
  percent: number;
  amount: number;
}

/** 本店定制项目报价行（价格来自 custom_quote_rules 表） */
export interface CustomQuoteItem {
  project: string;
  grade: string | null;
  unit: string;
  unitPrice: number;
  quantity: number;
  subtotal: number;
  note: string;
}

/** 本店产品报价汇总（后端根据商品库实算，AI 不参与定价） */
export interface ShopQuote {
  furnitureTotal: number;
  customTotal: number;
  total: number;
}

export interface LightingItem {
  name: string;
  /** 基础照明 / 氛围照明 / 局部照明 / 功能照明 */
  purpose: string;
  description: string;
}

export interface DesignPlan {
  id: string;
  name: string;
  style: string;
  /** 封面占位渐变（Tailwind class） */
  coverGradient: string;
  /** AI 推荐指数 0-100 */
  score: number;
  budget: number;
  tags: string[];
  suitableFor: string[];
  description: string;
  layoutSuggestions: string[];
  furnitureSuggestions: FurnitureItem[];
  colorPalette: ColorItem[];
  materials: MaterialItem[];
  lightingSuggestions: LightingItem[];
  budgetBreakdown: BudgetItem[];
  aiTips: string[];
  /** 二期新增：本店定制项目明细 + 产品报价汇总（LLM 方案经后端回填后携带） */
  customItems?: CustomQuoteItem[];
  shopQuote?: ShopQuote;
}

export type SavedDesignStatus = "草稿" | "已生成" | "已优化" | "已导出";

export interface SavedDesign {
  id: string;
  planId: string;
  name: string;
  style: string;
  budget: number;
  rooms: string[];
  status: SavedDesignStatus;
  isFavorite: boolean;
  createdAt: string;
  coverGradient: string;
}

export interface StyleCase {
  id: string;
  name: string;
  english: string;
  gradient: string;
  /** 风格案例轮播图，按展示顺序排列。 */
  images: string[];
  audience: string;
  colorKeywords: string[];
  budgetTendency: string;
  suitableLayout: string;
  description: string;
  materials: string[];
  palette: { name: string; hex: string }[];
  cautions: string[];
  furniture: string[];
}
