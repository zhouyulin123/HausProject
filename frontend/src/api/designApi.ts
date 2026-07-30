import type { DesignPlan } from "@/types/design";
import type { FurnitureItem } from "@/types/furniture";
import type { ImageAnalysis, UserRequirement } from "@/types/requirement";
import { mockDesigns } from "@/data/mockDesigns";
import { mockFurniture } from "@/data/mockFurniture";
import { getAiReply, uploadAnalysisFindings } from "@/data/mockChat";
import {
  readImageIds,
  readSessionId,
  readTaskId,
  writeImageIds,
  writeSessionId,
  writeTaskId,
} from "./sessionStorage";

/**
 * API 层：优先调用真实后端（FastAPI + MySQL + DeepSeek），
 * 后端不可用时自动降级到本地 mock，保证前端始终可演示。
 *
 * 后端接口（vite proxy 已代理 /api 与 /uploads 到 localhost:8010）：
 *   POST /api/upload/image                     文件上传 + 空间识别
 *   POST /api/design/tasks                     创建任务（携带结构化需求）
 *   POST /api/design/tasks/{id}/generate       DeepSeek 生成 3 套方案
 *   GET  /api/design/tasks/{id}/result         获取方案结果
 *   POST /api/design/chat                      DeepSeek 对话式需求确认
 */

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const browserStorage =
  typeof window !== "undefined" ? window.localStorage : null;

// 匿名客户上下文会持久化，刷新页面后可继续当前设计任务
let currentTaskId: number | null = browserStorage
  ? readTaskId(browserStorage)
  : null;
const uploadedImageIds: number[] = browserStorage
  ? readImageIds(browserStorage)
  : [];
const chatHistory: { role: string; content: string }[] = [];

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function rawRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(path, {
    ...init,
    headers,
  });
  if (!resp.ok) throw new ApiError(`${path} -> ${resp.status}`, resp.status);
  return resp.json() as Promise<T>;
}

let sessionPromise: Promise<string> | null = null;
let activeSessionId: string | null = null;

async function ensureAnonymousSession(): Promise<string> {
  if (!browserStorage) throw new Error("当前环境不支持匿名会话存储");
  if (activeSessionId) return activeSessionId;
  const storedId = readSessionId(browserStorage);
  if (storedId) {
    try {
      await rawRequest(`/api/sessions/${storedId}`);
      activeSessionId = storedId;
      return storedId;
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error;
      writeSessionId(browserStorage, null);
      writeTaskId(browserStorage, null);
      writeImageIds(browserStorage, []);
      currentTaskId = null;
      uploadedImageIds.splice(0);
    }
  }

  const created = await rawRequest<{ session_id: string }>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({}),
  });
  writeSessionId(browserStorage, created.session_id);
  activeSessionId = created.session_id;
  return created.session_id;
}

async function getAnonymousSessionId(): Promise<string> {
  if (!sessionPromise) {
    sessionPromise = ensureAnonymousSession().finally(() => {
      sessionPromise = null;
    });
  }
  return sessionPromise;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const sessionId = await getAnonymousSessionId();
  const headers = new Headers(init?.headers);
  headers.set("X-Session-ID", sessionId);
  return rawRequest<T>(path, { ...init, headers });
}

// ---------------------------------------------------------------- 视觉装饰
// 后端返回的方案不含渐变占位图信息，由前端按风格关键词补齐

const coverGradients: [string, string][] = [
  ["奶油", "bg-gradient-to-br from-[#f7efe2] via-[#ecd9bd] to-[#cfae83]"],
  ["原木", "bg-gradient-to-br from-[#efe3cd] via-[#dcc39a] to-[#b3906a]"],
  ["简约", "bg-gradient-to-br from-[#eeece7] via-[#d8d4cc] to-[#a8a296]"],
  ["轻奢", "bg-gradient-to-br from-[#efe6dc] via-[#d9c3ae] to-[#9b7d63]"],
  ["日式", "bg-gradient-to-br from-[#f1ede4] via-[#ddd2bf] to-[#a3937a]"],
  ["侘寂", "bg-gradient-to-br from-[#f1ede4] via-[#ddd2bf] to-[#a3937a]"],
  ["北欧", "bg-gradient-to-br from-[#f0f1ec] via-[#dbe0d3] to-[#a9b8a0]"],
  ["中古", "bg-gradient-to-br from-[#ece1cc] via-[#cfa97a] to-[#8a5f3c]"],
  ["法式", "bg-gradient-to-br from-[#f6ede4] via-[#e7cfc0] to-[#c09a86]"],
];

const fallbackCovers = [
  "bg-gradient-to-br from-[#f7efe2] via-[#ecd9bd] to-[#cfae83]",
  "bg-gradient-to-br from-[#eeece7] via-[#d8d4cc] to-[#a8a296]",
  "bg-gradient-to-br from-[#efe6dc] via-[#d9c3ae] to-[#9b7d63]",
];

const furnitureGradients = [
  "bg-gradient-to-br from-[#f5ede0] via-[#eaddc8] to-[#d9c3a5]",
  "bg-gradient-to-br from-[#e8d5b8] via-[#d8bd94] to-[#c2a173]",
  "bg-gradient-to-br from-[#faf6ee] via-[#f0e8d8] to-[#ddd0b8]",
  "bg-gradient-to-br from-[#e9dcc3] via-[#d4bd97] to-[#b89a6d]",
  "bg-gradient-to-br from-[#eee3cf] via-[#dcc9a6] to-[#c3a67a]",
  "bg-gradient-to-br from-[#e6e2d6] via-[#d3ccba] to-[#b5ab93]",
];

function decoratePlan(plan: DesignPlan, index: number): DesignPlan {
  const style = plan.style ?? "";
  const cover =
    coverGradients.find(([keyword]) => style.includes(keyword))?.[1] ??
    fallbackCovers[index % fallbackCovers.length];
  return {
    ...plan,
    coverGradient: plan.coverGradient || cover,
    furnitureSuggestions: (plan.furnitureSuggestions ?? []).map(
      (item: FurnitureItem, i: number) => ({
        ...item,
        gradient: item.gradient || furnitureGradients[i % furnitureGradients.length],
      }),
    ),
  };
}

// ---------------------------------------------------------------- 方案生成

function summarizeRequirement(r: UserRequirement): string {
  const parts = [
    r.rooms.length ? `改造空间：${r.rooms.join("、")}` : "",
    r.area ? `面积 ${r.area}㎡` : "",
    r.houseType,
    r.renovationType,
    r.budgetRange ? `预算 ${r.budgetRange}` : "",
    `常住 ${r.familySize} 人`,
    r.hasChildren ? "有儿童" : "",
    r.hasPets ? "有宠物" : "",
    r.hasElderly ? "有老人" : "",
    r.needStorage ? "需要大量收纳" : "",
    r.styles.length ? `喜欢${r.styles.join("、")}` : "",
    r.extraNotes,
  ];
  return parts.filter(Boolean).join("，");
}

// React StrictMode 开发模式下 effect 会双触发；LLM 生成又慢又贵，
// 用 in-flight 缓存让并发调用共享同一个请求
let inFlightGeneration: Promise<DesignPlan[]> | null = null;

export function generateDesigns(
  requirement: UserRequirement,
): Promise<DesignPlan[]> {
  if (!inFlightGeneration) {
    inFlightGeneration = doGenerateDesigns(requirement).finally(() => {
      inFlightGeneration = null;
    });
  }
  return inFlightGeneration;
}

/**
 * 从服务端恢复当前匿名会话最近生成的方案。
 *
 * 没有历史任务或任务已不存在时返回 null，由调用方决定是否创建新任务；
 * 网络和服务端错误继续抛出，避免把暂时故障误判成“没有历史方案”。
 */
export async function restoreCurrentDesigns(): Promise<DesignPlan[] | null> {
  if (!currentTaskId) return null;

  try {
    const result = await request<{ plans: DesignPlan[]; generator: string }>(
      `/api/design/tasks/${currentTaskId}/result`,
    );
    return result.plans.map(decoratePlan);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      currentTaskId = null;
      if (browserStorage) writeTaskId(browserStorage, null);
      return null;
    }
    throw error;
  }
}

async function doGenerateDesigns(
  requirement: UserRequirement,
): Promise<DesignPlan[]> {
  try {
    const task = await request<{ task_id: number }>("/api/design/tasks", {
      method: "POST",
      body: JSON.stringify({
        session_id: await getAnonymousSessionId(),
        user_input: summarizeRequirement(requirement),
        requirement,
        image_ids: uploadedImageIds,
      }),
    });
    currentTaskId = task.task_id;
    if (browserStorage) writeTaskId(browserStorage, currentTaskId);

    await request(`/api/design/tasks/${task.task_id}/generate`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    const result = await request<{ plans: DesignPlan[]; generator: string }>(
      `/api/design/tasks/${task.task_id}/result`,
    );
    console.info(`[designApi] 方案生成完成（generator=${result.generator}）`);
    return result.plans.map(decoratePlan);
  } catch (error) {
    console.warn("[designApi] 后端不可用，降级到本地 mock 方案", error);
    await delay(2200);
    const plans = [...mockDesigns];
    if (requirement.budgetRange === "3 万以下" || requirement.budgetRange === "3-8 万") {
      plans.sort((a, b) => a.budget - b.budget);
    }
    return plans;
  }
}

// ---------------------------------------------------------------- 图片上传

export async function analyzeRoomImage(file: File): Promise<ImageAnalysis> {
  const sizeText =
    file.size > 1024 * 1024
      ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
      : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  try {
    const form = new FormData();
    form.append("file", file);
    const data = await request<{
      image_id: number;
      analysis: {
        findings: string[];
        suggestions?: string[];
        space_type?: string;
        room_count?: string;
        source?: string;
      };
    }>("/api/upload/image", { method: "POST", body: form });
    uploadedImageIds.push(data.image_id);
    if (browserStorage) writeImageIds(browserStorage, uploadedImageIds);
    return {
      fileName: file.name,
      fileSize: sizeText,
      findings: data.analysis.findings,
      suggestions: data.analysis.suggestions ?? [],
      spaceType: data.analysis.space_type,
      roomCount: data.analysis.room_count,
      source: data.analysis.source ?? "vl",
    };
  } catch (error) {
    console.warn("[designApi] 上传接口不可用，降级到本地 mock 分析", error);
    await delay(1800);
    return {
      fileName: file.name,
      fileSize: sizeText,
      findings: uploadAnalysisFindings,
      source: "mock",
    };
  }
}

// ---------------------------------------------------------------- 商品库（自家家具）

interface BackendProduct {
  id: number;
  name: string;
  category: string | null;
  room: string | null;
  style: string | null;
  material: string | null;
  price_text: string;
  size: string | null;
  selling_point: string | null;
  alternative: string | null;
  image_url: string | null;
}

/** 从后端商品库拉取自家家具；后端不可用时降级到本地 mock 数据。 */
export async function fetchFurnitureCatalog(): Promise<FurnitureItem[]> {
  try {
    const data = await request<{ products: BackendProduct[] }>("/api/products");
    if (!data.products.length) throw new Error("商品库为空");
    console.info(`[designApi] 商品库加载完成（${data.products.length} 件）`);
    return data.products.map((p, i) => ({
      id: String(p.id),
      name: p.name,
      category: p.category ?? "其他",
      room: p.room ?? "客厅",
      style: p.style ?? "现代简约",
      material: p.material ?? "",
      priceRange: p.price_text,
      sizeSuggestion: p.size ?? "",
      // 商品库阶段的稳定伪评分；接入 AI 排序后替换
      matchScore: 86 + ((p.id * 7) % 13),
      reason: p.selling_point ?? "",
      alternative: p.alternative ?? "可选同风格系列其他款式",
      gradient: furnitureGradients[i % furnitureGradients.length],
      imageUrl: p.image_url ?? undefined,
    }));
  } catch (error) {
    console.warn("[designApi] 商品库不可用，降级到本地 mock 家具", error);
    return mockFurniture;
  }
}

// ---------------------------------------------------------------- 商品库管理（/admin）

export interface AdminProduct {
  id: number;
  sku: string | null;
  name: string;
  category: string | null;
  room: string | null;
  style: string | null;
  material: string | null;
  price: number;
  price_max: number | null;
  price_text: string;
  size: string | null;
  selling_point: string | null;
  alternative: string | null;
  image_url: string | null;
}

export interface QuoteRule {
  id: number;
  project_name: string;
  category: string;
  pricing_unit: string;
  material_grade: string | null;
  unit_price: number;
  description: string | null;
}

export async function fetchAdminProducts(): Promise<AdminProduct[]> {
  const data = await request<{ products: AdminProduct[] }>("/api/products");
  return data.products;
}

export async function saveProduct(
  product: Partial<AdminProduct> & { name: string; price: number },
): Promise<AdminProduct> {
  if (product.id) {
    return request<AdminProduct>(`/api/products/${product.id}`, {
      method: "PATCH",
      body: JSON.stringify(product),
    });
  }
  return request<AdminProduct>("/api/products", {
    method: "POST",
    body: JSON.stringify(product),
  });
}

export async function deleteProduct(id: number): Promise<void> {
  await request(`/api/products/${id}`, { method: "DELETE" });
}

export async function uploadProductImage(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const data = await request<{ image_url: string }>("/api/products/upload-image", {
    method: "POST",
    body: form,
  });
  return data.image_url;
}

export async function fetchQuoteRules(): Promise<QuoteRule[]> {
  const data = await request<{ rules: QuoteRule[] }>("/api/products/quote-rules");
  return data.rules;
}

export async function saveQuoteRule(
  rule: Partial<QuoteRule> & { project_name: string; unit_price: number },
): Promise<void> {
  if (rule.id) {
    await request(`/api/products/quote-rules/${rule.id}`, {
      method: "PATCH",
      body: JSON.stringify(rule),
    });
  } else {
    await request("/api/products/quote-rules", {
      method: "POST",
      body: JSON.stringify(rule),
    });
  }
}

export async function deleteQuoteRule(id: number): Promise<void> {
  await request(`/api/products/quote-rules/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------- 店铺设置

export interface ShopSettings {
  shop_name: string;
  phone: string | null;
  wechat: string | null;
  address: string | null;
  slogan: string | null;
  logo_url: string | null;
}

export async function fetchShopSettings(): Promise<ShopSettings> {
  return request<ShopSettings>("/api/shop");
}

export async function saveShopSettings(data: ShopSettings): Promise<ShopSettings> {
  return request<ShopSettings>("/api/shop", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function uploadShopLogo(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const data = await request<{ logo_url: string }>("/api/shop/logo", {
    method: "POST",
    body: form,
  });
  return data.logo_url;
}

// ---------------------------------------------------------------- 效果图生成

export function getCurrentTaskId(): number | null {
  return currentTaskId;
}

export interface RenderedEffect {
  imageUrl: string;
  /** controlnet（基于上传照片重绘）/ text2img（凭空生成） */
  mode: string;
}

/** 按需生成方案效果图（后端本地 SD，约 10-15 秒）。失败时抛错，由页面提示。 */
export async function renderEffectImage(
  planId: string,
  style: string,
  roomType?: string,
): Promise<RenderedEffect> {
  const data = await request<{ image_url: string; mode: string }>(
    "/api/design/render",
    {
      method: "POST",
      body: JSON.stringify({
        plan_id: planId,
        style,
        task_id: currentTaskId,
        room_type: roomType,
      }),
    },
  );
  return { imageUrl: data.image_url, mode: data.mode };
}

// ---------------------------------------------------------------- 提案 PDF 导出

/** 生成品牌提案 PDF（方案+效果图+报价单），返回可下载/转发的 URL。失败抛错。 */
export async function exportProposalPdf(plan: DesignPlan): Promise<string> {
  if (!currentTaskId) {
    throw new Error("当前没有可导出的设计任务");
  }
  const data = await request<{ pdf_url: string }>("/api/design/proposal-pdf", {
    method: "POST",
    body: JSON.stringify({ plan_id: plan.id, task_id: currentTaskId }),
  });
  return data.pdf_url;
}

// ---------------------------------------------------------------- 客户跟单

export interface CustomerRecord {
  id: number;
  name: string;
  phone: string | null;
  wechat: string | null;
  address: string | null;
  note: string | null;
  task_count: number;
  created_at: string | null;
}

export async function listCustomers(q?: string): Promise<CustomerRecord[]> {
  const data = await request<{ customers: CustomerRecord[] }>(
    `/api/customers${q ? `?q=${encodeURIComponent(q)}` : ""}`,
  );
  return data.customers;
}

export async function createCustomer(payload: {
  name: string;
  phone?: string;
  note?: string;
}): Promise<CustomerRecord> {
  return request<CustomerRecord>("/api/customers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** 把当前会话生成的方案任务关联到客户名下；无任务时返回 false */
export async function attachCurrentTaskToCustomer(customerId: number): Promise<boolean> {
  if (!currentTaskId) return false;
  await request(`/api/customers/${customerId}/attach-task`, {
    method: "POST",
    body: JSON.stringify({ task_id: currentTaskId }),
  });
  return true;
}

// ---------------------------------------------------------------- 对话

export async function sendChatMessage(text: string): Promise<string> {
  try {
    const data = await request<{ reply: string }>("/api/design/chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        task_id: currentTaskId,
        history: chatHistory.slice(-8),
      }),
    });
    chatHistory.push({ role: "user", content: text });
    chatHistory.push({ role: "ai", content: data.reply });
    return data.reply;
  } catch (error) {
    console.warn("[designApi] 对话接口不可用，降级到本地规则回复", error);
    await delay(1200 + Math.random() * 800);
    return getAiReply(text);
  }
}
