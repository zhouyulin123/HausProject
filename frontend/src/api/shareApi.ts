export class PublicShareUnavailableError extends Error {
  constructor() {
    super("分享链接不存在或已失效");
  }
}

export interface SharedFurniture {
  sku: string | null;
  name: string;
  category: string | null;
  room: string | null;
  style: string | null;
  material: string | null;
  price_range: string | null;
  size: string | null;
  reason: string | null;
  alternative: string | null;
  quantity: number | null;
  unit_price: number | null;
  subtotal: number | null;
}

export interface SharedColor {
  name: string;
  hex: string;
  usage: string | null;
}

export interface SharedMaterial {
  name: string;
  description: string | null;
}

export interface SharedLighting {
  name: string;
  purpose: string | null;
  description: string | null;
}

export interface SharedBudgetItem {
  name: string;
  percent: number | null;
  amount: number | null;
}

export interface SharedQuote {
  currency: string;
  furniture_total: number;
  custom_total: number;
  total: number;
  line_items: Array<{
    sku: string;
    quantity: number;
    unit_price: number;
    subtotal: number;
  }>;
  custom_line_items: Array<{
    project: string;
    grade: string | null;
    unit: string | null;
    quantity: number;
    unit_price: number;
    subtotal: number;
  }>;
}

export interface PublicPlanSnapshot {
  name: string;
  style: string | null;
  description: string | null;
  budget: number | null;
  tags: string[];
  suitable_for: string[];
  layout_suggestions: string[];
  ai_tips: string[];
  furniture: SharedFurniture[];
  colors: SharedColor[];
  materials: SharedMaterial[];
  lighting: SharedLighting[];
  budget_breakdown: SharedBudgetItem[];
  quote: SharedQuote | null;
}

export interface PublicPlanShare {
  expires_at: string;
  plan: PublicPlanSnapshot;
}

export async function fetchPublicPlanShare(token: string): Promise<PublicPlanShare> {
  const headers = new Headers({ Accept: "application/json" });
  const response = await fetch(`/api/shares/${encodeURIComponent(token)}`, {
    headers,
    credentials: "omit",
    cache: "no-store",
  });
  if (response.status === 404) throw new PublicShareUnavailableError();
  if (!response.ok) throw new Error("暂时无法读取分享方案");
  const payload = await response.json() as PublicPlanShare;
  if (!payload?.plan || typeof payload.plan.name !== "string") {
    throw new Error("分享方案响应格式无效");
  }
  return payload;
}
