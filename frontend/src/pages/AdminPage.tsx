import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { AlertTriangle, Boxes, Check, History, Pencil, Plus, RefreshCw, Ruler, Search, Store, Trash2, X } from "lucide-react";
import type { AdminCatalogReadiness, AdminProduct, QuoteRule } from "@/api/designApi";
import {
  ApiError,
  deleteProduct,
  deleteQuoteRule,
  fetchAdminCatalogReadiness,
  fetchAdminProducts,
  fetchQuoteRules,
  reviewProductModel,
  saveQuoteRule,
} from "@/api/designApi";
import ProductFormModal from "@/components/admin/ProductFormModal";
import ProductCommercialReviewPanel from "@/components/admin/ProductCommercialReviewPanel";
import ShopSettingsPanel from "@/components/admin/ShopSettingsPanel";
import PageTitle from "@/components/common/PageTitle";
import EmptyState from "@/components/common/EmptyState";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";
import { useAuthStore } from "@/store/useAuthStore";

type AdminTab = "products" | "quotes" | "shop";
type VerificationFilter = "all" | AdminProduct["verification_status"];

export interface PendingProductDeactivation {
  productId: number;
  recordVersion: number;
  idempotencyKey: string;
}

export type ProductDeactivationOutcome =
  | { outcome: "success" }
  | { outcome: "conflict"; message: string }
  | { outcome: "retryable_error"; message: string };

export async function submitProductDeactivation(
  pending: PendingProductDeactivation,
  remove: typeof deleteProduct,
  refresh: () => Promise<void>,
): Promise<ProductDeactivationOutcome> {
  try {
    await remove(
      pending.productId,
      pending.recordVersion,
      pending.idempotencyKey,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      await refresh();
      return {
        outcome: "conflict",
        message: "商品已被其他运营人员更新，目录已刷新，请核对后重新操作",
      };
    }
    return {
      outcome: "retryable_error",
      message: "下架结果暂时未知，可点击确认下架重试同一请求",
    };
  }
  await refresh();
  return { outcome: "success" };
}

function productDeactivationKey(product: AdminProduct): string {
  const operationId = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `product-deactivate-${product.id}-v${product.record_version}-${operationId}`;
}

const verificationLabels: Record<AdminProduct["verification_status"], string> = {
  draft: "待核验",
  verified: "已核验",
  rejected: "核验拒绝",
  expired: "核验过期",
};

const availabilityLabels: Record<AdminProduct["availability_status"], string> = {
  in_stock: "有库存",
  low_stock: "库存紧张",
  out_of_stock: "缺货",
  preorder: "预售",
  unknown: "库存状态未知",
};

const eligibilityReasonLabels: Record<string, string> = {
  inactive: "已下架",
  public_reference: "仅公开参考",
  provenance_unverified: "来源尚未核验",
  source_name_missing: "缺少来源名称",
  source_reference_missing: "缺少来源编号或链接",
  source_retrieved_at_missing: "缺少来源采集时间",
  source_retrieved_at_future: "来源采集时间晚于检查时间",
  price_observed_at_missing: "缺少价格观察时间",
  price_observed_at_future: "价格观察时间晚于检查时间",
  verification_required: "缺少商业核验",
  verification_rejected: "商业核验被拒绝",
  verification_expired: "商业核验已过期",
  verification_invalid: "核验状态无效",
  verified_at_missing: "缺少核验时间",
  verified_at_future: "核验时间晚于检查时间",
  verified_by_missing: "缺少核验负责人",
  data_version_unverified: "数据版本尚未正式发布",
  out_of_stock: "无可用库存",
  availability_unknown: "库存状态未知",
  lead_time_unknown: "交期未知",
  availability_invalid: "可售状态无效",
  insufficient_stock: "库存数量不足",
  price_validity_unknown: "价格有效期未知",
  price_not_started: "价格尚未生效",
  price_expired: "价格已过期",
  region_unknown: "销售地区未知",
  region_required: "需要指定地区",
  region_unavailable: "当前地区不可售",
  dimensions_missing: "缺少完整尺寸",
  dimensions_exceeded: "尺寸超出空间",
  budget_exceeded: "超出预算",
};

export function filterAdminProducts(
  products: AdminProduct[],
  keyword: string,
  verification: VerificationFilter,
): AdminProduct[] {
  const normalizedKeyword = keyword.trim().toLocaleLowerCase("zh-CN");
  return products.filter((product) => {
    if (verification !== "all" && product.verification_status !== verification) {
      return false;
    }
    if (!normalizedKeyword) return true;
    return [product.name, product.sku, product.source_name, product.source_product_id]
      .some((value) => value?.toLocaleLowerCase("zh-CN").includes(normalizedKeyword));
  });
}

export function ProductCommercialFacts({ product }: { product: AdminProduct }) {
  const reasonCodes = product.eligibility?.reason_codes ?? [];
  const leadTime = product.lead_time_days_min == null && product.lead_time_days_max == null
    ? "交期未录入"
    : `${product.lead_time_days_min ?? "?"}-${product.lead_time_days_max ?? "?"} 天`;
  return (
    <div className="mt-2 grid gap-x-5 gap-y-1 border-t border-cream-100 pt-2 text-xs text-stone-500 sm:grid-cols-2 lg:grid-cols-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Tag tone={product.verification_status === "verified" ? "sage" : "cream"}>
          {verificationLabels[product.verification_status]}
        </Tag>
        <Tag tone={product.eligibility?.eligible ? "sage" : "terra"}>
          {product.eligibility?.eligible ? "可推荐" : "不可推荐"}
        </Tag>
      </div>
      <span>{availabilityLabels[product.availability_status]} · 库存 {product.stock_quantity ?? "-"}</span>
      <span>{product.region_codes.length ? product.region_codes.join(" / ") : "地区未录入"} · {leadTime}</span>
      <span>{product.source_name || "来源未录入"} · {product.data_version} / r{product.record_version}</span>
      {reasonCodes.length > 0 && (
        <div className="flex flex-wrap gap-x-2 gap-y-1 text-terra-700 sm:col-span-2 lg:col-span-4">
          {reasonCodes.map((code) => (
            <span key={code}>{eligibilityReasonLabels[code] ?? code}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export function CatalogReadinessSummary({
  readiness,
  loading,
  error,
  onRetry,
}: {
  readiness: AdminCatalogReadiness | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  if (loading) {
    return <div className="h-24 animate-pulse border-y border-cream-200 bg-cream-100/60" />;
  }
  if (error || !readiness) {
    return (
      <div className="flex items-center justify-between gap-4 border-y border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <span className="inline-flex items-center gap-2"><AlertTriangle className="h-4 w-4" />{error || "目录就绪度暂不可用"}</span>
        <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
          <RefreshCw className="h-4 w-4" />重试
        </Button>
      </div>
    );
  }
  const blockers = Object.entries(readiness.reason_code_counts)
    .filter(([, count]) => count > 0)
    .sort(([, left], [, right]) => right - left)
    .slice(0, 5);
  return (
    <section className="border-y border-cream-200 bg-white/60 px-4 py-3" aria-label="商品目录就绪度">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div><p className="text-xs text-stone-400">核验地区</p><strong className="text-sm text-stone-800">{readiness.region}</strong></div>
        <div><p className="text-xs text-stone-400">目录总数</p><strong className="text-sm text-stone-800">{readiness.total}</strong></div>
        <div><p className="text-xs text-stone-400">可推荐</p><strong className="text-sm text-sage-700">{readiness.eligible_total}</strong></div>
        <div><p className="text-xs text-stone-400">不可推荐</p><strong className="text-sm text-terra-700">{readiness.ineligible_total}</strong></div>
      </div>
      {blockers.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-cream-100 pt-2 text-xs text-stone-600">
          {blockers.map(([code, count]) => (
            <span key={code}>{eligibilityReasonLabels[code] ?? code} <strong>{count}</strong></span>
          ))}
        </div>
      )}
    </section>
  );
}

export default function AdminPage() {
  const isAdmin = useAuthStore((state) => state.user?.role === "admin");
  const [tab, setTab] = useState<AdminTab>("products");
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [rules, setRules] = useState<QuoteRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [verificationFilter, setVerificationFilter] = useState<VerificationFilter>("all");
  const [readiness, setReadiness] = useState<AdminCatalogReadiness | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(true);
  const [readinessError, setReadinessError] = useState("");
  const [regionInput, setRegionInput] = useState("CN-SH");
  const [readinessRegion, setReadinessRegion] = useState("CN-SH");
  const [catalogError, setCatalogError] = useState("");
  const [editing, setEditing] = useState<AdminProduct | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<PendingProductDeactivation | null>(null);
  const [commercialProductId, setCommercialProductId] = useState<number | null>(null);

  const reload = useCallback(async () => {
    setCatalogError("");
    try {
      const [p, r] = await Promise.all([fetchAdminProducts(), fetchQuoteRules()]);
      setProducts(p);
      setRules(r);
    } catch (error) {
      setCatalogError(error instanceof Error ? error.message : "商品目录加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadReadiness = useCallback(async (region: string) => {
    setReadinessLoading(true);
    setReadinessError("");
    try {
      setReadiness(await fetchAdminCatalogReadiness(region));
    } catch (error) {
      setReadiness(null);
      setReadinessError(error instanceof Error ? error.message : "目录就绪度加载失败");
    } finally {
      setReadinessLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    void loadReadiness(readinessRegion);
  }, [loadReadiness, readinessRegion]);

  const filteredProducts = useMemo(
    () =>
      filterAdminProducts(products, keyword, verificationFilter),
    [products, keyword, verificationFilter],
  );
  const commercialProduct = commercialProductId == null
    ? null
    : products.find((product) => product.id === commercialProductId) ?? null;

  const openNew = () => {
    setEditing(null);
    setShowModal(true);
  };
  const openEdit = (p: AdminProduct) => {
    setEditing(p);
    setShowModal(true);
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <PageTitle
        title="商品库管理"
        description="维护成品家具与定制报价规则。只有通过商业核验和地区、库存、价格有效期门禁的商品才会进入 AI 方案与报价单。（内部使用）"
      />

      {/* Tab 切换 */}
      <div className="mt-6 flex gap-2">
        <button
          type="button"
          onClick={() => setTab("products")}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-all ${
            tab === "products"
              ? "bg-sage-600 text-white shadow-card"
              : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
          }`}
        >
          <Boxes className="h-4 w-4" />
          成品家具 ({products.length})
        </button>
        <button
          type="button"
          onClick={() => setTab("quotes")}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-all ${
            tab === "quotes"
              ? "bg-sage-600 text-white shadow-card"
              : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
          }`}
        >
          <Ruler className="h-4 w-4" />
          定制报价 ({rules.length})
        </button>
        <button
          type="button"
          onClick={() => setTab("shop")}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium transition-all ${
            tab === "shop"
              ? "bg-sage-600 text-white shadow-card"
              : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
          }`}
        >
          <Store className="h-4 w-4" />
          店铺设置
        </button>
      </div>

      {tab === "products" && (
        <div className="mt-6">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                const normalized = regionInput.trim().toUpperCase();
                if (!normalized) return;
                if (normalized === readinessRegion) {
                  void loadReadiness(normalized);
                } else {
                  setReadinessRegion(normalized);
                }
              }}
            >
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-stone-500">就绪度地区</span>
                <input
                  value={regionInput}
                  onChange={(event) => setRegionInput(event.target.value)}
                  className="w-32 rounded-lg border border-cream-300 bg-white px-3 py-2 text-sm uppercase text-stone-700 outline-none focus:border-sage-500 focus:ring-2 focus:ring-sage-100"
                  placeholder="CN-SH"
                />
              </label>
              <Button type="submit" variant="outline" size="sm">查询</Button>
            </form>
          </div>
          <CatalogReadinessSummary
            readiness={readiness}
            loading={readinessLoading}
            error={readinessError}
            onRetry={() => void loadReadiness(readinessRegion)}
          />

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="mt-4 flex flex-col gap-2 sm:flex-row">
              <div className="relative sm:w-72">
                <Search className="absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 text-stone-300" />
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索产品名、SKU 或来源"
                  className="w-full rounded-xl border border-cream-300 bg-white/80 py-2.5 pr-4 pl-10 text-sm text-stone-700 outline-none placeholder:text-stone-300 focus:border-sage-500 focus:ring-2 focus:ring-sage-100"
                />
              </div>
              <label>
                <span className="sr-only">核验状态</span>
                <select
                  value={verificationFilter}
                  onChange={(event) => setVerificationFilter(event.target.value as VerificationFilter)}
                  className="w-full rounded-xl border border-cream-300 bg-white/80 px-3.5 py-2.5 text-sm text-stone-700 outline-none focus:border-sage-500 focus:ring-2 focus:ring-sage-100 sm:w-36"
                >
                  <option value="all">全部核验状态</option>
                  <option value="draft">待核验</option>
                  <option value="verified">已核验</option>
                  <option value="rejected">核验拒绝</option>
                  <option value="expired">核验过期</option>
                </select>
              </label>
            </div>
            <Button className="mt-4" onClick={openNew}>
              <Plus className="h-4 w-4" />
              新增产品
            </Button>
          </div>

          {catalogError ? (
            <div className="mt-5 flex items-center justify-between gap-4 border-y border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <span>{catalogError}</span>
              <Button type="button" variant="ghost" size="sm" onClick={() => void reload()}>
                <RefreshCw className="h-4 w-4" />重试
              </Button>
            </div>
          ) : loading ? (
            <div className="mt-5 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-2xl bg-cream-100/70" />
              ))}
            </div>
          ) : filteredProducts.length === 0 ? (
            <div className="mt-6">
              <EmptyState
                icon={Boxes}
                title="没有产品"
                description="点击「新增产品」录入第一件，或用 Excel 批量导入。"
              />
            </div>
          ) : (
            <div className="mt-5 space-y-2">
              {filteredProducts.map((p) => (
                <div
                  key={p.id}
                  className="flex flex-col gap-3 rounded-lg border border-cream-200 bg-white/80 p-3 transition-shadow hover:shadow-card sm:flex-row sm:items-start"
                >
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <div className="h-14 w-16 shrink-0 overflow-hidden rounded-lg bg-cream-100">
                      {p.image_url ? (
                        <img src={p.image_url} alt={p.name} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-xs text-stone-300">
                          无图
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-stone-800">{p.name}</span>
                        {p.sku && <Tag tone="cream">{p.sku}</Tag>}
                        {p.model_status === "ready" && <Tag tone="sage">3D</Tag>}
                        {p.model_status === "pending_review" && <Tag tone="cream">3D 待审核</Tag>}
                        {p.model_status === "rejected" && <Tag tone="terra">3D 已拒绝</Tag>}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-stone-400">
                        {p.category} · {p.room} · {p.style} · {p.material}
                      </p>
                      <ProductCommercialFacts product={p} />
                    </div>
                  </div>
                  <div className="flex min-w-0 shrink-0 flex-wrap items-center justify-between gap-2 border-t border-cream-100 pt-2 sm:border-0 sm:pt-0">
                    <span className="font-display text-sm font-semibold text-terra-600">
                      {p.price_text}
                    </span>
                    <div className="flex min-w-0 flex-wrap items-center justify-end gap-1">
                    {p.model_status === "pending_review" && (
                      <>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="批准模型"
                          onClick={async () => {
                            await reviewProductModel(p.id, "approve");
                            void reload();
                            void loadReadiness(readinessRegion);
                          }}
                        >
                          <Check className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="拒绝模型"
                          onClick={async () => {
                            await reviewProductModel(p.id, "reject");
                            void reload();
                            void loadReadiness(readinessRegion);
                          }}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </>
                    )}
                    <Button variant="ghost" size="sm" title="编辑商品" onClick={() => openEdit(p)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      title={isAdmin ? "商业审核与审计" : "查看商业审计"}
                      onClick={() => setCommercialProductId(p.id)}
                    >
                      <History className="h-4 w-4" />
                    </Button>
                    {pendingDelete?.productId === p.id ? (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="terra"
                          size="sm"
                          onClick={async () => {
                            const result = await submitProductDeactivation(
                              pendingDelete,
                              deleteProduct,
                              async () => {
                                await Promise.all([
                                  reload(),
                                  loadReadiness(readinessRegion),
                                ]);
                              },
                            );
                            if (result.outcome !== "success") {
                              setCatalogError(result.message);
                            }
                            if (result.outcome !== "retryable_error") {
                              setPendingDelete(null);
                            }
                          }}
                        >
                          确认下架
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setPendingDelete(null)}>
                          取消
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        title="下架商品"
                        onClick={() => setPendingDelete({
                          productId: p.id,
                          recordVersion: p.record_version,
                          idempotencyKey: productDeactivationKey(p),
                        })}
                      >
                        <Trash2 className="h-4 w-4 text-stone-400" />
                      </Button>
                    )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {commercialProduct && (
        <ProductCommercialReviewPanel
          product={commercialProduct}
          canReview={isAdmin}
          onClose={() => setCommercialProductId(null)}
          onProductRefresh={async () => {
            await Promise.all([reload(), loadReadiness(readinessRegion)]);
          }}
        />
      )}

      {tab === "quotes" && (
        <QuoteRulesPanel rules={rules} onChanged={reload} />
      )}

      {tab === "shop" && <ShopSettingsPanel />}

      <AnimatePresence>
        {showModal && (
          <ProductFormModal
            initial={editing}
            onClose={() => setShowModal(false)}
            onSaved={() => {
              setShowModal(false);
              void reload();
              void loadReadiness(readinessRegion);
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------- 定制报价面板

const units = ["㎡", "延米", "米", "项"];

function QuoteRulesPanel({
  rules,
  onChanged,
}: {
  rules: QuoteRule[];
  onChanged: () => Promise<void>;
}) {
  const [draft, setDraft] = useState({
    project_name: "",
    category: "柜类定制",
    pricing_unit: "㎡",
    material_grade: "",
    unit_price: 0,
    region_codes: [] as string[],
    region_codes_input: "",
    waste_rate_bps: 0,
    minimum_quantity: 0,
    installation_fee: 0,
    shipping_fee: 0,
    tax_rate_bps: 0,
    data_version: "draft-v1",
    description: "",
  });

  const add = async () => {
    if (!draft.project_name.trim() || !draft.material_grade.trim() || !draft.unit_price) return;
    const { region_codes_input: _, ...payload } = draft;
    await saveQuoteRule({
      ...payload,
      region_codes: draft.region_codes_input
        .split(",")
        .map((code) => code.trim().toUpperCase())
        .filter(Boolean),
    });
    setDraft({
      ...draft,
      project_name: "",
      material_grade: "",
      unit_price: 0,
      description: "",
    });
    void onChanged();
  };

  const inputClass =
    "rounded-xl border border-cream-300 bg-white/80 px-3 py-2 text-sm text-stone-700 placeholder:text-stone-300 outline-none focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

  return (
    <div className="mt-6">
      {/* 新增行 */}
      <div className="grid gap-2 rounded-2xl border border-cream-200 bg-white/80 p-4 sm:grid-cols-2 lg:grid-cols-5">
        <input
          className={inputClass}
          placeholder="项目名（定制衣柜）"
          value={draft.project_name}
          onChange={(e) => setDraft((d) => ({ ...d, project_name: e.target.value }))}
        />
        <input
          className={inputClass}
          placeholder="材料档位（多层实木）"
          value={draft.material_grade}
          onChange={(e) => setDraft((d) => ({ ...d, material_grade: e.target.value }))}
        />
        <input
          type="number"
          className={inputClass}
          placeholder="单价"
          value={draft.unit_price || ""}
          onChange={(e) => setDraft((d) => ({ ...d, unit_price: Number(e.target.value) }))}
        />
        <select
          className={inputClass}
          value={draft.pricing_unit}
          onChange={(e) => setDraft((d) => ({ ...d, pricing_unit: e.target.value }))}
        >
          {units.map((u) => (
            <option key={u}>{u}</option>
          ))}
        </select>
        <Button onClick={() => void add()} disabled={!draft.project_name.trim() || !draft.material_grade.trim() || !draft.unit_price}>
          <Plus className="h-4 w-4" />
          添加
        </Button>
        <input
          className={inputClass}
          placeholder="地区代码，逗号分隔；留空为全国"
          value={draft.region_codes_input}
          onChange={(e) => setDraft((d) => ({ ...d, region_codes_input: e.target.value }))}
        />
        <input
          type="number"
          min="0"
          max="100"
          step="0.01"
          className={inputClass}
          placeholder="损耗率 %"
          value={draft.waste_rate_bps / 100 || ""}
          onChange={(e) => setDraft((d) => ({ ...d, waste_rate_bps: Math.round(Number(e.target.value) * 100) }))}
        />
        <input
          type="number"
          min="0"
          step="0.1"
          className={inputClass}
          placeholder="最低计价量"
          value={draft.minimum_quantity || ""}
          onChange={(e) => setDraft((d) => ({ ...d, minimum_quantity: Number(e.target.value) }))}
        />
        <input
          type="number"
          min="0"
          className={inputClass}
          placeholder="安装费"
          value={draft.installation_fee || ""}
          onChange={(e) => setDraft((d) => ({ ...d, installation_fee: Number(e.target.value) }))}
        />
        <input
          type="number"
          min="0"
          className={inputClass}
          placeholder="运输费"
          value={draft.shipping_fee || ""}
          onChange={(e) => setDraft((d) => ({ ...d, shipping_fee: Number(e.target.value) }))}
        />
        <input
          type="number"
          min="0"
          max="100"
          step="0.01"
          className={inputClass}
          placeholder="税率 %"
          value={draft.tax_rate_bps / 100 || ""}
          onChange={(e) => setDraft((d) => ({ ...d, tax_rate_bps: Math.round(Number(e.target.value) * 100) }))}
        />
        <input
          className={inputClass}
          placeholder="数据版本"
          value={draft.data_version}
          onChange={(e) => setDraft((d) => ({ ...d, data_version: e.target.value }))}
        />
      </div>

      <div className="mt-4 overflow-x-auto rounded-2xl border border-cream-200">
        <table className="min-w-[960px] w-full text-sm">
          <thead className="bg-cream-100 text-left text-xs text-stone-500">
            <tr>
              <th className="px-4 py-2.5 font-medium">项目</th>
              <th className="px-4 py-2.5 font-medium">材料档位</th>
              <th className="px-4 py-2.5 text-right font-medium">单价</th>
              <th className="px-4 py-2.5 font-medium">单位</th>
              <th className="px-4 py-2.5 font-medium">地区</th>
              <th className="px-4 py-2.5 font-medium">附加费用</th>
              <th className="px-4 py-2.5 font-medium">版本</th>
              <th className="px-4 py-2.5"></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id} className="border-t border-cream-100">
                <td className="px-4 py-2.5 font-medium text-stone-700">{r.project_name}</td>
                <td className="px-4 py-2.5 text-stone-500">{r.material_grade ?? "-"}</td>
                <td className="px-4 py-2.5 text-right font-medium text-terra-600">
                  ¥{r.unit_price.toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-stone-500">/{r.pricing_unit}</td>
                <td className="px-4 py-2.5 text-stone-500">
                  {r.region_codes.length ? r.region_codes.join(", ") : "全国"}
                </td>
                <td className="px-4 py-2.5 text-xs text-stone-500">
                  损耗 {r.waste_rate_bps / 100}% · 最低 {r.minimum_quantity} · 安装 ¥{r.installation_fee} · 运输 ¥{r.shipping_fee} · 税 {r.tax_rate_bps / 100}%
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-stone-500">
                  {r.data_version} / r{r.record_version}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <button
                    type="button"
                    onClick={async () => {
                      await deleteQuoteRule(r.id, r.record_version);
                      void onChanged();
                    }}
                    className="text-stone-400 hover:text-terra-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
