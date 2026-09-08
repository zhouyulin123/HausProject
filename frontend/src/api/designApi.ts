import type { DesignPlan } from "@/types/design";
import type {
  FurnitureDataOrigin,
  FurnitureItem,
  Furniture3DSpec,
} from "@/types/furniture";
import type { ImageAnalysis, UserRequirement } from "@/types/requirement";
import type { RoomModel } from "@/types/roomModel";
import type {
  AgentExecutionEvent,
  AgentExitReason,
  AgentPendingQuestion,
  AgentSceneReference,
} from "@/types/agent";
import type {
  CustomFurniturePreviewResult,
  CustomFurnitureSpecPatch,
} from "@/types/customFurniture";
import type {
  DesignFeedbackEventRequest,
  DesignFeedbackEventResponse,
} from "@/types/feedback";
import type {
  BlenderRenderJob,
  BlenderRenderProfile,
  DesignScene,
  DesignSceneVersion,
  SceneDocument,
  SceneAgentCommandResult,
  SceneOperation,
  SceneSource,
  SceneValidationReport,
} from "@/types/scene";
import { mockDesigns } from "@/data/mockDesigns";
import { mockFurniture } from "@/data/mockFurniture";
import { uploadAnalysisFindings } from "@/data/mockChat";
import {
  readImageIds,
  readSessionId,
  readTaskId,
  writeImageIds,
  writeSessionId,
  writeTaskId,
} from "./sessionStorage";
import { readToken } from "./authApi";
import { CustomFurnitureDraftConflictError } from "@/lib/customFurnitureDraftQueue";

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
const demoFallbackEnabled = import.meta.env.VITE_DEMO_MODE === "true";

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

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
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
  if (!resp.ok) {
    let detail: unknown;
    try {
      const body = await resp.json() as { detail?: unknown };
      detail = body.detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(`${path} -> ${resp.status}`, resp.status, detail);
  }
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
    const taskId = await createDesignTask(requirement);
    return await generateDesignsForTask(taskId);
  } catch (error) {
    if (!demoFallbackEnabled) throw error;
    console.warn("[designApi] 后端不可用，降级到本地 mock 方案", error);
    await delay(2200);
    const plans = [...mockDesigns];
    if (requirement.budgetRange === "3 万以下" || requirement.budgetRange === "3-8 万") {
      plans.sort((a, b) => a.budget - b.budget);
    }
    return plans;
  }
}

interface GenerationStatus {
  run_id: number;
  status:
    | "queued"
    | "running"
    | "completed"
    | "failed"
    | "dead_letter"
    | "cost_limit_exceeded"
    | "provider_unavailable"
    | "cancelled";
  progress: number;
  current_node: string | null;
  error_message: string | null;
  execution_deadline_at?: string | null;
  dead_lettered_at?: string | null;
}

async function waitForGeneration(
  taskId: number,
  timeoutMs = 180_000,
  expectedRunId?: number,
): Promise<GenerationStatus> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const generation = await request<GenerationStatus>(
      `/api/design/tasks/${taskId}/generation`,
    );
    if (expectedRunId !== undefined && generation.run_id !== expectedRunId) {
      throw new Error("生成任务引用已变化，已停止自动恢复");
    }
    if (generation.status === "completed") return generation;
    if (
      [
        "failed",
        "dead_letter",
        "cost_limit_exceeded",
        "provider_unavailable",
        "cancelled",
      ].includes(
        generation.status,
      )
    ) {
      const fallbackMessage = generation.status === "cancelled"
        ? "方案生成已取消"
        : generation.status === "dead_letter"
          ? "方案生成超过执行限制，已停止并等待人工处理"
          : generation.status === "cost_limit_exceeded"
            ? "方案生成达到成本上限，需要人工确认"
          : generation.status === "provider_unavailable"
            ? "模型供应商暂时不可用，需要人工处理"
          : "方案生成失败，请稍后重试";
      throw new Error(generation.error_message || fallbackMessage);
    }
    await delay(1000);
  }
  throw new Error("方案生成超时，请稍后在当前任务中继续查看");
}

// ---------------------------------------------------------------- 图片上传

export async function analyzeRoomImage(
  file: File,
  taskId?: number,
): Promise<ImageAnalysis> {
  const sizeText =
    file.size > 1024 * 1024
      ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
      : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  try {
    const form = new FormData();
    form.append("file", file);
    if (taskId) form.append("task_id", String(taskId));
    const data = await request<{
      image_id: number;
      analysis: {
        findings: string[];
        suggestions?: string[];
        space_type?: string;
        room_count?: string;
        source?: string;
        room_model?: RoomModel | null;
      };
    }>("/api/upload/image", { method: "POST", body: form });
    uploadedImageIds.push(data.image_id);
    if (browserStorage) writeImageIds(browserStorage, uploadedImageIds);
    return {
      fileName: file.name,
      fileSize: sizeText,
      imageId: data.image_id,
      findings: data.analysis.findings,
      suggestions: data.analysis.suggestions ?? [],
      spaceType: data.analysis.space_type,
      roomCount: data.analysis.room_count,
      source: data.analysis.source ?? "vl",
      roomModel: data.analysis.room_model ?? null,
    };
  } catch (error) {
    if (!demoFallbackEnabled) throw error;
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

export interface RoomModelCalibration {
  roomId?: string;
  widthM: number;
  depthM: number;
  ceilingHeightM?: number;
}

/** 用户校准主空间真实尺寸，写回图片的 RoomModel。 */
export async function calibrateRoomModel(
  imageId: number,
  calibration: RoomModelCalibration,
): Promise<RoomModel> {
  const data = await request<{ image_id: number; room_model: RoomModel }>(
    `/api/upload/images/${imageId}/room-model`,
    {
      method: "PUT",
      body: JSON.stringify({
        roomId: calibration.roomId,
        widthM: calibration.widthM,
        depthM: calibration.depthM,
        ceilingHeightM: calibration.ceilingHeightM,
      }),
    },
  );
  return data.room_model;
}

// ---------------------------------------------------------------- 商品库（自家家具）

interface BackendProduct {
  id: number;
  sku: string | null;
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
  model_url: string | null;
  model_status: "missing" | "pending_review" | "ready" | "rejected" | "failed";
  asset_mode: "approved_glb" | "parametric" | "fallback";
  fallback_reason:
    | "glb_unavailable"
    | "glb_pending_review"
    | "glb_rejected"
    | "glb_marked_failed"
    | "glb_metadata_invalid"
    | "asset_contract_missing"
    | "catalog_product_unavailable"
    | "glb_load_failed"
    | null;
  model_width_mm: number | null;
  model_height_mm: number | null;
  model_depth_mm: number | null;
  model_license: string | null;
  model_source: string | null;
  model_spec_json: Furniture3DSpec | null;
  data_origin: FurnitureDataOrigin;
  source_name: string | null;
  source_url: string | null;
  eligibility: {
    eligible: boolean;
    reason_codes: string[];
  };
}

/** 从后端商品库拉取自家家具；后端不可用时降级到本地 mock 数据。 */
export async function fetchFurnitureCatalog(
  options: { fallbackToMock?: boolean } = {},
): Promise<FurnitureItem[]> {
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
      reason: p.selling_point ?? "",
      alternative: p.alternative ?? "可选同风格系列其他款式",
      gradient: furnitureGradients[i % furnitureGradients.length],
      imageUrl: p.image_url ?? undefined,
      sku: p.sku ?? undefined,
      modelUrl: p.model_url ?? undefined,
      modelStatus: p.model_status,
      assetMode: p.asset_mode,
      fallbackReason: p.fallback_reason ?? undefined,
      modelDimensionsMm: {
        width: p.model_width_mm,
        height: p.model_height_mm,
        depth: p.model_depth_mm,
      },
      modelSpecJson: p.model_spec_json ?? undefined,
      dataOrigin: p.data_origin ?? "unknown",
      sourceName: p.source_name ?? undefined,
      sourceUrl: p.source_url ?? undefined,
      catalogEligibility: {
        eligible: p.eligibility.eligible,
        reasonCodes: p.eligibility.reason_codes,
      },
    }));
  } catch (error) {
    const fallbackToMock = options.fallbackToMock ?? demoFallbackEnabled;
    if (!fallbackToMock) {
      const catalogError = new Error("商品库加载失败，请检查后端服务和商品数据");
      (catalogError as Error & { cause?: unknown }).cause = error;
      throw catalogError;
    }
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
  model_url: string | null;
  model_status: "missing" | "pending_review" | "ready" | "rejected" | "failed";
  model_width_mm: number | null;
  model_height_mm: number | null;
  model_depth_mm: number | null;
  model_license: string | null;
  model_source: string | null;
  model_reviewed_at: string | null;
  model_reviewed_by: string | null;
  model_review_note: string | null;
}

export interface QuoteRule {
  id: number;
  project_name: string;
  category: string;
  pricing_unit: string;
  material_grade: string | null;
  unit_price: number;
  region_codes: string[];
  waste_rate_bps: number;
  minimum_quantity: number;
  installation_fee: number;
  shipping_fee: number;
  tax_rate_bps: number;
  data_version: string;
  record_version: number;
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

export async function uploadProductModel(
  productId: number,
  file: File,
): Promise<AdminProduct> {
  const form = new FormData();
  form.append("file", file);
  return request<AdminProduct>(`/api/products/${productId}/model`, {
    method: "POST",
    body: form,
  });
}

export async function reviewProductModel(
  productId: number,
  decision: "approve" | "reject",
  note?: string,
): Promise<AdminProduct> {
  return request<AdminProduct>(`/api/products/${productId}/model-review`, {
    method: "POST",
    body: JSON.stringify({ decision, note: note || null }),
  });
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

export type EffectRenderStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "dead_letter"
  | "cancelled"
  | "provider_unavailable";

export interface EffectRenderJob {
  jobId: number;
  taskId: number;
  planVersionId: number;
  sceneId: number;
  sceneVersion: number;
  status: EffectRenderStatus;
  progress: number;
  attemptCount: number;
  maxAttempts: number;
  imageUrl: string | null;
  mode: string | null;
  errorMessage: string | null;
}

interface EffectRenderJobWire {
  job_id: number;
  task_id: number;
  plan_version_id: number;
  scene_id: number;
  scene_version: number;
  status: EffectRenderStatus;
  progress: number;
  attempt_count: number;
  max_attempts: number;
  image_url?: string | null;
  mode?: string | null;
  error_message?: string | null;
}

function mapEffectRenderJob(data: EffectRenderJobWire): EffectRenderJob {
  return {
    jobId: data.job_id,
    taskId: data.task_id,
    planVersionId: data.plan_version_id,
    sceneId: data.scene_id,
    sceneVersion: data.scene_version,
    status: data.status,
    progress: data.progress,
    attemptCount: data.attempt_count,
    maxAttempts: data.max_attempts,
    imageUrl: data.image_url ?? null,
    mode: data.mode ?? null,
    errorMessage: data.error_message ?? null,
  };
}

export async function queueEffectRender(
  planVersionId: number,
  sceneId: number,
  sceneVersion: number,
  idempotencyKey: string,
): Promise<EffectRenderJob> {
  if (!currentTaskId) throw new Error("当前没有可渲染的设计任务");
  const data = await request<EffectRenderJobWire>("/api/design/render", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      task_id: currentTaskId,
      plan_version_id: planVersionId,
      scene_id: sceneId,
      scene_version: sceneVersion,
    }),
  });
  return mapEffectRenderJob(data);
}

export async function fetchEffectRender(jobId: number): Promise<EffectRenderJob> {
  return mapEffectRenderJob(
    await request<EffectRenderJobWire>(`/api/design/render/${jobId}`),
  );
}

export async function fetchLatestEffectRender(
  planVersionId: number,
  sceneId: number,
  sceneVersion: number,
): Promise<EffectRenderJob | null> {
  try {
    const data = await request<EffectRenderJobWire>(
      `/api/design/render?plan_version_id=${planVersionId}&scene_id=${sceneId}&scene_version=${sceneVersion}`,
    );
    return mapEffectRenderJob(data);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function cancelEffectRender(jobId: number): Promise<EffectRenderJob> {
  return mapEffectRenderJob(
    await request<EffectRenderJobWire>(
      `/api/design/render/${jobId}/cancel`,
      { method: "POST" },
    ),
  );
}

// ---------------------------------------------------------------- 方案分享

export interface CreatedPlanShare {
  token: string;
  shareUrl: string;
  expiresAt: string;
}

export async function createPlanShare(
  planVersionId: number,
  expiresInHours = 168,
): Promise<CreatedPlanShare> {
  const data = await request<{
    token: string;
    share_url: string;
    expires_at: string;
  }>("/api/design/shares", {
    method: "POST",
    body: JSON.stringify({
      plan_version_id: planVersionId,
      expires_in_hours: expiresInHours,
    }),
  });
  return {
    token: data.token,
    shareUrl: data.share_url,
    expiresAt: data.expires_at,
  };
}

export async function revokePlanShare(token: string): Promise<void> {
  await request<{ status: "revoked" }>(
    `/api/design/shares/${encodeURIComponent(token)}/revoke`,
    { method: "POST" },
  );
}

// ---------------------------------------------------------------- 提案 PDF 导出

/** 生成品牌提案 PDF（方案+效果图+报价单），返回可下载/转发的 URL。失败抛错。 */
export async function exportProposalPdf(plan: DesignPlan): Promise<string> {
  if (!currentTaskId) {
    throw new Error("当前没有可导出的设计任务");
  }
  if (!plan.planVersionId) {
    throw new Error("当前方案没有可追溯的服务端版本，无法导出");
  }
  const data = await request<{ pdf_url: string }>("/api/design/proposal-pdf", {
    method: "POST",
    body: JSON.stringify({
      plan_version_id: plan.planVersionId,
      task_id: currentTaskId,
    }),
  });
  return data.pdf_url;
}

// ---------------------------------------------------------------- 我的方案（后端）

export interface MyDesignItem {
  task_id: number;
  created_at: string | null;
  style: string | null;
  space_type: string | null;
  plans: DesignPlan[];
}

async function authedRequest<T>(path: string): Promise<T> {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(path, { headers });
  if (!resp.ok) throw new ApiError(`${path} -> ${resp.status}`, resp.status);
  return resp.json() as Promise<T>;
}

/** 拉取登录用户的历史方案（每个任务附带最新版本方案快照）。 */
export async function fetchMyDesigns(): Promise<MyDesignItem[]> {
  const data = await authedRequest<{
    designs: (Omit<MyDesignItem, "plans"> & { plans: DesignPlan[] })[];
  }>("/api/design/tasks/mine");
  return data.designs.map((item) => ({
    ...item,
    plans: item.plans.map(decoratePlan),
  }));
}

/** 按方案版本 ID 拉取单个方案快照，供详情页本地无缓存时兜底。 */
export async function fetchPlanByVersion(
  planVersionId: number,
): Promise<DesignPlan> {
  const data = await authedRequest<{ plan: DesignPlan }>(
    `/api/design/plan-versions/${planVersionId}`,
  );
  return decoratePlan(data.plan, 0);
}

export interface RefinePlanResult {
  plan: DesignPlan;
  version: number;
  message: string;
}

/** 按自然语言指令在现有方案上精准修改，返回新版本方案。 */
export async function refinePlan(
  taskId: number,
  planId: string,
  instruction: string,
): Promise<RefinePlanResult> {
  const data = await request<{
    plan: DesignPlan;
    version: number;
    message: string;
  }>(`/api/design/tasks/${taskId}/plans/${planId}/refine`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
  data.plan = decoratePlan(data.plan, 0);
  return data;
}

// ---------------------------------------------------------------- 3D 场景

/** 为服务端不可变方案版本创建第一版 3D 场景。 */
export async function createDesignScene(
  planVersionId: number,
  scene: SceneDocument,
  source: SceneSource = "manual",
): Promise<DesignScene> {
  return request<DesignScene>(
    `/api/design/plan-versions/${planVersionId}/scene`,
    {
      method: "POST",
      body: JSON.stringify({ scene, source }),
    },
  );
}

/** 让后端确定性布局引擎为方案自动生成可编辑 3D 初稿（幂等）。 */
export async function createAutoLayoutScene(
  planVersionId: number,
): Promise<DesignScene> {
  return request<DesignScene>(
    `/api/design/plan-versions/${planVersionId}/auto-layout`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

/** 按方案版本恢复场景，页面刷新时无需预先知道 sceneId。 */
export async function fetchDesignSceneByPlanVersion(
  planVersionId: number,
): Promise<DesignScene> {
  return request<DesignScene>(
    `/api/design/plan-versions/${planVersionId}/scene`,
  );
}

const sceneLoadRequests = new Map<number, Promise<DesignScene>>();

async function doLoadOrCreateDesignScene(
  planVersionId: number,
  initialScene: SceneDocument,
): Promise<DesignScene> {
  try {
    return await fetchDesignSceneByPlanVersion(planVersionId);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error;
  }

  // 优先后端确定性布局引擎自动生成可编辑 3D 初稿（幂等）
  try {
    return await createAutoLayoutScene(planVersionId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      return fetchDesignSceneByPlanVersion(planVersionId);
    }
    // 后端不可用 / 方案无可用商品 / 无房间模型时，回退前端确定性初始布局
  }

  try {
    return await createDesignScene(planVersionId, initialScene);
  } catch (error) {
    // React StrictMode 或其他设备可能已在 GET 与 POST 之间创建成功。
    if (error instanceof ApiError && error.status === 409) {
      return fetchDesignSceneByPlanVersion(planVersionId);
    }
    throw error;
  }
}

/**
 * 恢复方案场景；不存在时用确定性初始布局创建。
 * 同一页面的并发调用共享请求，避免 StrictMode 重复创建。
 */
export function loadOrCreateDesignScene(
  planVersionId: number,
  initialScene: SceneDocument,
): Promise<DesignScene> {
  const existing = sceneLoadRequests.get(planVersionId);
  if (existing) return existing;

  const requestPromise = doLoadOrCreateDesignScene(
    planVersionId,
    initialScene,
  ).finally(() => {
    sceneLoadRequests.delete(planVersionId);
  });
  sceneLoadRequests.set(planVersionId, requestPromise);
  return requestPromise;
}

/** 恢复 3D 场景的当前版本。 */
export async function fetchDesignScene(sceneId: number): Promise<DesignScene> {
  return request<DesignScene>(`/api/design/scenes/${sceneId}`);
}

/** 将同一任务内已成功保存的定制草稿加入版本化房间场景。 */
export async function addCustomFurnitureDraftToScene(
  sceneId: number,
  payload: {
    baseVersion: number;
    clientMutationId: string;
    draftClientMutationId: string;
    position: { x: number; z: number };
    rotationY?: number;
  },
): Promise<DesignScene> {
  return request<DesignScene>(
    `/api/design/scenes/${sceneId}/custom-furniture-items`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

/** 基于已知版本保存场景；服务端会拒绝过期版本，避免静默覆盖。 */
export async function updateDesignScene(
  sceneId: number,
  baseVersion: number,
  scene: SceneDocument,
  source: SceneSource = "manual",
  mutation?: {
    clientMutationId: string;
    movedInstanceIds: string[];
    roomId?: string | null;
  },
): Promise<DesignScene> {
  return request<DesignScene>(`/api/design/scenes/${sceneId}`, {
    method: "PUT",
    body: JSON.stringify({
      base_version: baseVersion,
      scene,
      source,
      ...(mutation
        ? {
            client_mutation_id: mutation.clientMutationId,
            moved_instance_ids: mutation.movedInstanceIds,
            feedback_room_id: mutation.roomId,
          }
        : {}),
    }),
  });
}

/** 获取场景的不可变历史版本，最新版本排在最前。 */
export async function fetchDesignSceneVersions(
  sceneId: number,
): Promise<DesignSceneVersion[]> {
  const data = await request<{ versions: DesignSceneVersion[] }>(
    `/api/design/scenes/${sceneId}/versions`,
  );
  return data.versions;
}

/** 按当前商品库和空间规则重新校验已保存的场景。 */
export async function validateDesignScene(
  sceneId: number,
): Promise<SceneValidationReport> {
  return request<SceneValidationReport>(
    `/api/design/scenes/${sceneId}/validate`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

/** 让 Scene Agent 把自然语言转换成白名单操作，并返回新场景版本。 */
export async function runSceneAgentCommand(
  sceneId: number,
  baseVersion: number,
  instruction: string,
): Promise<SceneAgentCommandResult> {
  return request<SceneAgentCommandResult>(
    `/api/design/scenes/${sceneId}/agent-command`,
    {
      method: "POST",
      body: JSON.stringify({
        baseVersion,
        instruction,
      }),
    },
  );
}

export interface DemoAgentCommandResult {
  message: string;
  operations: SceneOperation[];
  scene: SceneDocument;
}

export interface DemoConversationTurn {
  instruction: string;
  message: string;
  operations: SceneOperation[];
  affectedInstanceIds: string[];
}

/** demo 3D 页：让 AI 把指令解析成白名单操作，前端本地执行。 */
export async function runDemoAgentCommand(
  instruction: string,
  scene: SceneDocument,
  history: DemoConversationTurn[] = [],
): Promise<DemoAgentCommandResult> {
  return request<DemoAgentCommandResult>("/api/demo/agent-command", {
    method: "POST",
    body: JSON.stringify({ instruction, scene, history: history.slice(-8) }),
  });
}

/** 创建独立 Blender Worker 消费的版本化渲染任务。 */
export async function createBlenderRenderJob(
  sceneId: number,
  baseVersion: number,
  profile: BlenderRenderProfile,
): Promise<BlenderRenderJob> {
  return request<BlenderRenderJob>(
    `/api/design/scenes/${sceneId}/render-jobs`,
    {
      method: "POST",
      body: JSON.stringify({
        baseVersion,
        profile,
      }),
    },
  );
}

/** 查询 Blender 渲染任务进度和最终产物。 */
export async function fetchBlenderRenderJob(
  sceneId: number,
  jobId: number,
): Promise<BlenderRenderJob> {
  return request<BlenderRenderJob>(
    `/api/design/scenes/${sceneId}/render-jobs/${jobId}`,
  );
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

export interface DesignChatContext {
  /** 由工作台项目显式绑定的服务端任务；null 表示项目尚未创建服务端任务。 */
  taskId: number | null;
  history: { role: string; content: string }[];
}

/** 创建统一工作台项目。返回值就是路由 projectId，不生成前端替代编号。 */
export async function createDesignTask(
  requirement: UserRequirement,
  activeMode: AgentActiveMode = "catalog_design",
): Promise<number> {
  const task = await request<{ task_id: number }>("/api/design/tasks", {
    method: "POST",
    body: JSON.stringify({
      session_id: await getAnonymousSessionId(),
      user_input: summarizeRequirement(requirement),
      active_mode: activeMode,
      requirement,
      image_ids: uploadedImageIds,
    }),
  });
  currentTaskId = task.task_id;
  if (browserStorage) writeTaskId(browserStorage, currentTaskId);
  return task.task_id;
}

/** 在已有 DesignTask 上生成方案，避免工作台另建第二个任务。 */
export async function generateDesignsForTask(taskId: number): Promise<DesignPlan[]> {
  currentTaskId = taskId;
  if (browserStorage) writeTaskId(browserStorage, currentTaskId);
  await request<{ run_id: number; status: string }>(
    `/api/design/tasks/${taskId}/generate-async`,
    {
      method: "POST",
      headers: { "Idempotency-Key": `design-generation-task-${taskId}-v1` },
      body: JSON.stringify({}),
    },
  );
  await waitForGeneration(taskId);
  return fetchDesignTaskPlans(taskId);
}

/** 读取指定任务已持久化的真实方案版本，不创建任务也不触发生成。 */
export async function fetchDesignTaskPlans(taskId: number): Promise<DesignPlan[]> {
  const result = await request<{
    plans: DesignPlan[];
    generator: string;
    revision_version?: number;
  }>(
    `/api/design/tasks/${taskId}/result`,
  );
  return result.plans.map((plan, index) => ({
    ...decoratePlan(plan, index),
    revisionVersion: result.revision_version,
  }));
}

export type PlanMutationAction = "adopt" | "remove" | "replace";

export interface PlanMutationResponse {
  revision_version: number;
  plan: DesignPlan;
  scene: DesignScene;
  feedback: DesignFeedbackEventResponse;
}

export async function mutateWorkspacePlan(
  taskId: number,
  payload: {
    clientMutationId: string;
    baseRevisionVersion: number;
    planVersionId: number;
    action: PlanMutationAction;
    sourceInstanceId?: string;
    targetSku?: string;
    roomId?: string | null;
  },
): Promise<PlanMutationResponse> {
  const result = await request<PlanMutationResponse>(
    `/api/design/tasks/${taskId}/plan-mutations`,
    {
      method: "POST",
      body: JSON.stringify({
        client_mutation_id: payload.clientMutationId,
        base_revision_version: payload.baseRevisionVersion,
        plan_version_id: payload.planVersionId,
        action: payload.action,
        source_instance_id: payload.sourceInstanceId,
        target_sku: payload.targetSku,
        placement_mode: payload.action === "adopt" ? "auto_place" : undefined,
        room_id: payload.roomId,
      }),
    },
  );
  return {
    ...result,
    plan: {
      ...decoratePlan(result.plan, 0),
      revisionVersion: result.revision_version,
    },
  };
}

export type AgentActiveMode =
  | "catalog_design"
  | "custom_furniture"
  | "room_reconstruction";

export type AgentTaskStatus =
  | "draft"
  | "analyzing"
  | "waiting_user"
  | "ready"
  | "running"
  | "waiting_approval"
  | "completed"
  | "needs_human"
  | "failed"
  | "cancelled";

export interface AgentTurnRequest {
  client_turn_id: string;
  message: string;
  active_mode: AgentActiveMode;
  active_room_id?: string | null;
  scene_id?: number | null;
  base_scene_version?: number | null;
  selected_instance_id?: string | null;
  answers?: {
    space_type?: string;
    style?: string;
    budget_min?: number;
    budget_max?: number;
    room_width_m?: number;
    room_depth_m?: number;
    ceiling_height_m?: number;
  };
  custom_furniture_spec?: CustomFurnitureSpecPatch;
}

export type AgentEvent = AgentExecutionEvent;

export interface AgentEventFeedResponse {
  events: AgentExecutionEvent[];
  has_more: boolean;
  next_before_id: number | null;
}

export interface AgentTurnResponse {
  task_id: number;
  turn_id: number;
  state_version: number;
  status: AgentTaskStatus;
  active_mode: AgentActiveMode;
  active_room_id: string | null;
  intent: string;
  reply: string;
  state: {
    status: AgentTaskStatus;
    current_node: string;
    active_room_id: string | null;
    facts: Record<string, unknown>;
    fact_evidence: Record<string, Record<string, unknown>>;
    step_count: number;
    retry_count: number;
    max_steps: number;
    max_retries: number;
    pending_questions: AgentPendingQuestion[];
    hard_errors: string[];
    custom_furniture_spec: CustomFurnitureSpecPatch | null;
    approval_required: boolean;
    exit_reason: AgentExitReason;
    run_id: number | null;
    cost_cny: number | null;
    cost_reserved_cny: number;
    cost_limit_cny: number | null;
    execution_deadline_at: string | null;
    cancel_requested_at: string | null;
    turn_execution_deadline_at: string | null;
  };
  pending_questions: AgentPendingQuestion[];
  events: AgentEvent[];
  approval_required: boolean;
  scene_ref: AgentSceneReference | null;
  run_id: number | null;
  exit_reason: AgentExitReason;
  result: CustomFurniturePreviewResult | Record<string, unknown> | null;
}

export interface DesignAgentStateResponse {
  task_id: number;
  state_version: number;
  status: AgentTaskStatus;
  active_mode: AgentActiveMode;
  active_room_id: string | null;
  intent: string;
  current_node: string;
  facts: Record<string, unknown>;
  fact_evidence: Record<string, Record<string, unknown>>;
  pending_questions: AgentPendingQuestion[];
  step_count: number;
  retry_count: number;
  max_steps: number;
  max_retries: number;
  hard_errors: string[];
  custom_furniture_spec: CustomFurnitureSpecPatch | null;
  custom_furniture_draft: CustomFurnitureSpecPatch | null;
  custom_furniture_draft_ref?: {
    client_mutation_id: string;
    state_version: number;
  } | null;
  approval_required: boolean;
  scene_ref: AgentSceneReference | null;
  run_id: number | null;
  cost_cny: number | null;
  cost_reserved_cny: number;
  cost_limit_cny: number | null;
  execution_deadline_at: string | null;
  cancel_requested_at: string | null;
  turn_execution_deadline_at: string | null;
  exit_reason: AgentExitReason;
  result: CustomFurniturePreviewResult | Record<string, unknown> | null;
  /** 服务端持久化历史；刷新时覆盖本地瞬时消息缓存。 */
  messages: { id: number; role: "user" | "ai"; content: string; created_at: string | null }[];
}

export interface AgentApproval {
  id: number;
  task_id: number;
  turn_id: number;
  approval_type: "quote_review" | "construction_risk" | "quality_gate";
  status: "pending" | "approved" | "rejected";
  request_reason: string;
  reason_code: string;
  request_context: Record<string, unknown>;
  requested_at: string;
  client_decision_id: string | null;
  decision: "approve" | "reject" | null;
  conclusion: string | null;
  decided_by_type: string | null;
  decided_by_id: string | null;
  decided_at: string | null;
}

export async function fetchAgentApprovals(taskId: number): Promise<AgentApproval[]> {
  const response = await request<{ approvals: AgentApproval[] }>(
    `/api/design/tasks/${taskId}/agent-approvals`,
  );
  return response.approvals;
}

export async function decideAgentApproval(
  taskId: number,
  approvalId: number,
  payload: {
    clientDecisionId: string;
    decision: "approve" | "reject";
    conclusion: string;
  },
): Promise<AgentApproval> {
  return request<AgentApproval>(
    `/api/design/tasks/${taskId}/agent-approvals/${approvalId}/decision`,
    {
      method: "POST",
      body: JSON.stringify({
        client_decision_id: payload.clientDecisionId,
        decision: payload.decision,
        conclusion: payload.conclusion,
      }),
    },
  );
}

export async function saveCustomFurnitureDraft(
  taskId: number,
  payload: {
    clientMutationId: string;
    baseStateVersion: number;
    spec: CustomFurnitureSpecPatch;
  },
): Promise<{
  task_id: number;
  state_version: number;
  custom_furniture_spec: CustomFurnitureSpecPatch;
}> {
  try {
    return await request(`/api/design/tasks/${taskId}/custom-furniture-draft`, {
      method: "PUT",
      body: JSON.stringify({
        client_mutation_id: payload.clientMutationId,
        base_state_version: payload.baseStateVersion,
        custom_furniture_spec: payload.spec,
      }),
    });
  } catch (error) {
    const detail = error instanceof ApiError && error.status === 409
      && typeof error.detail === "object" && error.detail !== null
      ? error.detail as Record<string, unknown>
      : null;
    if (
      detail?.code === "agent_state_conflict"
      && typeof detail.state_version === "number"
    ) {
      throw new CustomFurnitureDraftConflictError({
        stateVersion: detail.state_version,
        customFurnitureDraft:
          typeof detail.custom_furniture_draft === "object"
          ? detail.custom_furniture_draft as CustomFurnitureSpecPatch
          : null,
        sceneRef:
          typeof detail.scene_ref === "object"
          ? detail.scene_ref as AgentSceneReference
          : null,
      });
    }
    throw error;
  }
}

/** 新工作台唯一对话写入口；client_turn_id 为服务端幂等键。 */
export async function sendAgentTurn(
  taskId: number,
  turn: AgentTurnRequest,
): Promise<AgentTurnResponse> {
  return request<AgentTurnResponse>(`/api/design/tasks/${taskId}/agent-turns`, {
    method: "POST",
    body: JSON.stringify(turn),
  });
}

/** 刷新工作台时从服务端恢复编排状态，前端缓存不是事实源。 */
export async function fetchDesignAgentState(
  taskId: number,
): Promise<DesignAgentStateResponse> {
  return request<DesignAgentStateResponse>(
    `/api/design/tasks/${taskId}/agent-state`,
  );
}

export async function fetchDesignAgentEvents(
  taskId: number,
  options: { limit?: number; beforeId?: number } = {},
): Promise<AgentEventFeedResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options.limit ?? 50));
  if (options.beforeId !== undefined) {
    params.set("before_id", String(options.beforeId));
  }
  return request<AgentEventFeedResponse>(
    `/api/design/tasks/${taskId}/agent-events?${params.toString()}`,
  );
}

export async function resumeAgentGeneration(
  taskId: number,
  runId: number,
): Promise<{
  checkpoint: DesignAgentStateResponse;
  plans: DesignPlan[];
}> {
  try {
    await waitForGeneration(taskId, 180_000, runId);
  } catch (error) {
    const checkpoint = await fetchDesignAgentState(taskId);
    if (
      checkpoint.run_id === runId
      && ["needs_human", "cancelled"].includes(checkpoint.status)
    ) {
      return { checkpoint, plans: [] };
    }
    throw error;
  }
  const [checkpoint, plans] = await Promise.all([
    fetchDesignAgentState(taskId),
    fetchDesignTaskPlans(taskId),
  ]);
  if (checkpoint.run_id !== runId) {
    throw new Error("Agent 状态与生成任务引用不一致");
  }
  return { checkpoint, plans };
}

/** 记录任务级结构化反馈；调用方负责持有 client_event_id 以安全重试。 */
export async function sendDesignFeedbackEvent(
  taskId: number,
  event: DesignFeedbackEventRequest,
): Promise<DesignFeedbackEventResponse> {
  return request<DesignFeedbackEventResponse>(
    `/api/design/tasks/${taskId}/feedback-events`,
    { method: "POST", body: JSON.stringify(event) },
  );
}

export async function sendChatMessage(
  text: string,
  context?: DesignChatContext,
): Promise<string> {
  try {
    const data = await request<{ reply: string }>("/api/design/chat", {
      method: "POST",
      body: JSON.stringify({
        message: text,
        task_id: context ? context.taskId : currentTaskId,
        history: context ? context.history.slice(-8) : chatHistory.slice(-8),
      }),
    });
    // 旧页面仍使用模块内历史；工作台项目的历史由项目 Store 独立持久化。
    if (!context) {
      chatHistory.push({ role: "user", content: text });
      chatHistory.push({ role: "ai", content: data.reply });
    }
    return data.reply;
  } catch (error) {
    console.warn("[designApi] 对话接口不可用", error);
    return "AI 服务暂时不可用，请稍后再试。";
  }
}
