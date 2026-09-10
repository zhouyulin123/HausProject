import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, History, Loader2, ShieldCheck, X } from "lucide-react";
import {
  ApiError,
  fetchProductAuditEvents,
  reviewProductCommercially,
  type AdminProduct,
  type CommercialReviewDecision,
  type ProductAuditEvent,
} from "@/api/designApi";
import Button from "@/components/common/Button";

export interface PendingCommercialReview {
  productId: number;
  expectedRecordVersion: number;
  decision: CommercialReviewDecision;
  note: string | null;
  idempotencyKey: string;
}

export type CommercialReviewOutcome =
  | { outcome: "success" }
  | { outcome: "conflict"; message: string }
  | { outcome: "validation_error"; message: string }
  | { outcome: "retryable_error"; message: string }
  | { outcome: "failure"; message: string };

const eligibilityReasonLabels: Record<string, string> = {
  inactive: "商品已下架",
  public_reference: "仅为公开参考数据",
  provenance_unverified: "商业来源尚未核验",
  source_name_missing: "缺少来源名称",
  source_reference_missing: "缺少来源编号或链接",
  source_retrieved_at_missing: "缺少来源采集时间",
  source_retrieved_at_future: "来源采集时间晚于检查时间",
  price_observed_at_missing: "缺少价格观察时间",
  price_observed_at_future: "价格观察时间晚于检查时间",
  verification_required: "缺少商业核验",
  verification_rejected: "商业核验已被拒绝",
  verification_expired: "商业核验已过期",
  verification_invalid: "核验状态无效",
  verified_at_missing: "缺少核验时间",
  verified_at_future: "核验时间晚于检查时间",
  verified_by_missing: "缺少核验负责人",
  data_version_unverified: "数据版本尚未正式发布",
  out_of_stock: "没有可用库存",
  availability_unknown: "库存状态未知",
  lead_time_unknown: "交期未知",
  availability_invalid: "可售状态无效",
  insufficient_stock: "库存数量不足",
  price_validity_unknown: "价格有效期未知",
  price_not_started: "价格尚未生效",
  price_expired: "价格已过期",
  region_unknown: "销售地区未知",
  region_required: "需要指定销售地区",
  region_unavailable: "当前地区不可售",
  dimensions_missing: "缺少完整尺寸",
  dimensions_exceeded: "尺寸超出空间限制",
  budget_exceeded: "价格超出预算",
};

const eventLabels: Record<string, string> = {
  commercial_created: "创建商品",
  commercial_patch: "编辑商业事实",
  commercial_deactivate: "停用商品",
  commercial_excel_created: "Excel 新增商品",
  commercial_excel_updated: "Excel 更新商品",
  commercial_review_approve: "商业审核批准",
  commercial_review_reject: "商业审核拒绝",
};

const fieldLabels: Record<string, string> = {
  name: "商品名称",
  sku: "SKU",
  category: "品类",
  room: "空间",
  style: "风格",
  material: "材质",
  price: "价格",
  price_max: "价格上限",
  size: "展示尺寸",
  selling_point: "卖点摘要",
  alternative: "替代说明摘要",
  image_url: "商品图片",
  data_origin: "数据来源类型",
  source_name: "来源名称",
  source_url: "来源链接",
  source_product_id: "来源产品编号",
  source_retrieved_at: "来源采集时间",
  price_observed_at: "价格观察时间",
  price_note: "价格备注摘要",
  source_metadata: "来源元数据摘要",
  model_width_mm: "模型宽度",
  model_height_mm: "模型高度",
  model_depth_mm: "模型深度",
  model_license: "模型授权摘要",
  model_source: "模型来源摘要",
  availability_status: "可售状态",
  stock_quantity: "库存数量",
  region_codes: "销售地区",
  lead_time_days_min: "最短交期",
  lead_time_days_max: "最长交期",
  price_valid_from: "价格生效时间",
  price_valid_to: "价格失效时间",
  data_version: "数据版本",
  alternative_skus: "替代 SKU",
  is_active: "启用状态",
  verification_status: "核验状态",
  verified_at: "核验时间",
  verified_by: "核验人",
  record_version: "记录版本",
  review_note: "审核备注摘要",
};

const summaryFields = new Set([
  "selling_point",
  "alternative",
  "price_note",
  "source_metadata",
  "model_license",
  "model_source",
  "review_note",
]);
const localPathPattern = /^(?:[A-Za-z]:[\\/]|\\\\|\/(?:Users|home|var|tmp)\/)/i;

function errorDetail(error: ApiError): Record<string, unknown> | null {
  return error.detail && typeof error.detail === "object" && !Array.isArray(error.detail)
    ? error.detail as Record<string, unknown>
    : null;
}

export function commercialReviewErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) {
    const detail = errorDetail(error);
    const reasonCodes = Array.isArray(detail?.reason_codes)
      ? detail.reason_codes.filter((code): code is string => typeof code === "string")
      : [];
    if (reasonCodes.length > 0) {
      return `暂不能批准：${reasonCodes.map((code) => eligibilityReasonLabels[code] ?? code).join("；")}`;
    }
    return typeof error.detail === "string"
      ? error.detail
      : "商业核验信息未通过校验";
  }
  if (error instanceof ApiError && error.status === 409) {
    return "商品状态已变化，目录已刷新，请核对最新事实后重新操作";
  }
  return error instanceof Error ? error.message : "商业审核失败，请稍后重试";
}

export async function submitCommercialReview(
  pending: PendingCommercialReview,
  review: typeof reviewProductCommercially,
  refresh: () => Promise<void>,
): Promise<CommercialReviewOutcome> {
  try {
    await review(
      pending.productId,
      {
        decision: pending.decision,
        expectedRecordVersion: pending.expectedRecordVersion,
        ...(pending.note == null ? {} : { note: pending.note }),
      },
      pending.idempotencyKey,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      await refresh();
      return { outcome: "conflict", message: commercialReviewErrorMessage(error) };
    }
    if (error instanceof ApiError && error.status === 422) {
      return { outcome: "validation_error", message: commercialReviewErrorMessage(error) };
    }
    if (error instanceof TypeError || (error instanceof ApiError && error.status >= 500)) {
      return {
        outcome: "retryable_error",
        message: "审核结果暂时未知，可重试同一请求；系统不会自动重复审核",
      };
    }
    return { outcome: "failure", message: commercialReviewErrorMessage(error) };
  }
  await refresh();
  return { outcome: "success" };
}

function sanitizedUrl(value: string): string {
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.hostname}${url.port ? `:${url.port}` : ""}${url.pathname}`;
  } catch {
    return "链接已隐藏";
  }
}

function summaryValue(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "无";
  const summary = value as Record<string, unknown>;
  const parts: string[] = [];
  if (summary.present === true) parts.push("已记录");
  if (typeof summary.char_count === "number") parts.push(`字符数 ${summary.char_count}`);
  if (typeof summary.entry_count === "number") parts.push(`条目数 ${summary.entry_count}`);
  if (typeof summary.sha256 === "string" && summary.sha256) {
    parts.push(`SHA-256 ${summary.sha256}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "无";
}

export function formatAuditValue(field: string, value: unknown): string {
  if (value == null || value === "") return "无";
  if (summaryFields.has(field)) return summaryValue(value);
  if (field === "source_url" || field === "image_url") {
    return typeof value === "string" ? sanitizedUrl(value) : "链接已隐藏";
  }
  if (typeof value === "string") {
    return localPathPattern.test(value.trim()) ? "内容已隐藏" : value;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value
      .filter((item) => ["string", "number", "boolean"].includes(typeof item))
      .map(String)
      .join("、") || "无";
  }
  return "结构化值已隐藏";
}

export function CommercialReviewControls({
  canReview,
  status,
  busy,
  onApprove,
  onReject,
}: {
  canReview: boolean;
  status: AdminProduct["verification_status"];
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  if (!canReview) {
    return <p className="text-xs text-stone-500">仅管理员可执行商业审核，厂家账号可查看审计记录。</p>;
  }
  return (
    <div className="flex min-w-0 flex-wrap gap-2">
      <Button type="button" size="sm" disabled={busy || status === "verified"} onClick={onApprove}>
        <Check className="h-4 w-4" />批准
      </Button>
      <Button type="button" variant="terra" size="sm" disabled={busy} onClick={onReject}>
        <X className="h-4 w-4" />拒绝
      </Button>
    </div>
  );
}

export function ProductAuditTimeline({ events }: { events: ProductAuditEvent[] }) {
  if (events.length === 0) {
    return <p className="py-6 text-center text-sm text-stone-400">暂无商业审计记录</p>;
  }
  return (
    <ol className="space-y-3">
      {events.map((event) => (
        <li key={event.id} className="min-w-0 border-l-2 border-sage-300 bg-cream-50/70 px-3 py-2.5">
          <div className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-stone-800">
                {eventLabels[event.event_type] ?? event.event_type}
              </p>
              <p className="break-all text-xs text-stone-500">
                {event.actor} · 版本 r{event.resulting_record_version}
              </p>
            </div>
            <time className="shrink-0 text-xs text-stone-400" dateTime={event.created_at}>
              {new Date(event.created_at).toLocaleString("zh-CN")}
            </time>
          </div>
          {event.changed_fields.length > 0 && (
            <dl className="mt-2 space-y-1 border-t border-cream-200 pt-2 text-xs">
              {event.changed_fields.map((field) => {
                const change = event.changes[field];
                if (!change) return null;
                return (
                  <div key={field} className="grid min-w-0 gap-0.5 sm:grid-cols-[8rem_minmax(0,1fr)]">
                    <dt className="font-medium text-stone-500">{fieldLabels[field] ?? field}</dt>
                    <dd className="min-w-0 break-all text-stone-700">
                      {formatAuditValue(field, change.before)} → {formatAuditValue(field, change.after)}
                    </dd>
                  </div>
                );
              })}
            </dl>
          )}
        </li>
      ))}
    </ol>
  );
}

export function createPendingCommercialReview(
  product: Pick<AdminProduct, "id" | "record_version">,
  decision: CommercialReviewDecision,
  note: string,
  createOperationId: () => string = () => globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`,
): PendingCommercialReview {
  const normalizedNote = note.trim();
  if (decision === "reject" && !normalizedNote) {
    throw new Error("拒绝商业核验时必须填写原因");
  }
  return {
    productId: product.id,
    expectedRecordVersion: product.record_version,
    decision,
    note: decision === "reject" ? normalizedNote : null,
    idempotencyKey: `commercial-review-${product.id}-v${product.record_version}-${decision}-${createOperationId()}`,
  };
}

export default function ProductCommercialReviewPanel({
  product,
  canReview,
  onClose,
  onProductRefresh,
}: {
  product: AdminProduct;
  canReview: boolean;
  onClose: () => void;
  onProductRefresh: () => Promise<void>;
}) {
  const [events, setEvents] = useState<ProductAuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [rejectNote, setRejectNote] = useState("");
  const [pending, setPending] = useState<PendingCommercialReview | null>(null);

  const loadAudit = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await fetchProductAuditEvents(product.id);
      setEvents(result.items);
    } catch (auditError) {
      setError(auditError instanceof Error ? auditError.message : "审计记录加载失败");
    } finally {
      setLoading(false);
    }
  }, [product.id]);

  useEffect(() => {
    void loadAudit();
  }, [loadAudit]);

  const refreshAll = useCallback(async () => {
    await Promise.all([onProductRefresh(), loadAudit()]);
  }, [loadAudit, onProductRefresh]);

  const execute = async (request: PendingCommercialReview) => {
    setBusy(true);
    setError("");
    setMessage("");
    const result = await submitCommercialReview(request, reviewProductCommercially, refreshAll);
    setBusy(false);
    if (result.outcome === "success") {
      setPending(null);
      setShowReject(false);
      setRejectNote("");
      setMessage(request.decision === "approve" ? "商业审核已批准" : "商业审核已拒绝");
      return;
    }
    setError(result.message);
    if (result.outcome !== "retryable_error") setPending(null);
  };

  const beginReview = (decision: CommercialReviewDecision) => {
    let request: PendingCommercialReview;
    try {
      request = createPendingCommercialReview(product, decision, rejectNote);
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "商业审核请求无效");
      return;
    }
    setPending(request);
    void execute(request);
  };

  const retryPending = () => {
    if (pending) void execute(pending);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 p-0 sm:items-center sm:p-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="commercial-review-title"
        className="flex max-h-[92dvh] w-full min-w-0 flex-col overflow-hidden rounded-t-lg bg-white shadow-xl sm:max-w-3xl sm:rounded-lg"
      >
        <header className="flex items-start justify-between gap-3 border-b border-cream-200 px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-xs font-medium text-sage-700">
              <ShieldCheck className="h-4 w-4" />商业核验与追溯
            </p>
            <h2 id="commercial-review-title" className="mt-1 break-words text-base font-semibold text-stone-900">
              {product.name}
            </h2>
            <p className="mt-0.5 break-all text-xs text-stone-500">
              {product.sku || `商品 #${product.id}`} · 当前 r{product.record_version} · {product.verification_status}
            </p>
          </div>
          <Button type="button" variant="ghost" size="sm" title="关闭" onClick={onClose} disabled={busy}>
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="min-w-0 flex-1 overflow-y-auto px-4 py-4 sm:px-5">
          <div className="border-b border-cream-200 pb-4">
            <CommercialReviewControls
              canReview={canReview}
              status={product.verification_status}
              busy={busy || pending != null}
              onApprove={() => beginReview("approve")}
              onReject={() => setShowReject(true)}
            />
            {canReview && showReject && (
              <div className="mt-3 min-w-0 border-l-2 border-terra-300 pl-3">
                <label htmlFor="commercial-reject-note" className="block text-xs font-semibold text-stone-600">
                  拒绝原因
                </label>
                <textarea
                  id="commercial-reject-note"
                  value={pending?.decision === "reject" ? pending.note ?? "" : rejectNote}
                  disabled={busy || pending != null}
                  maxLength={500}
                  onChange={(event) => setRejectNote(event.target.value)}
                  className="mt-1 min-h-20 w-full resize-y rounded-lg border border-cream-300 px-3 py-2 text-sm text-stone-700 outline-none focus:border-terra-400"
                  placeholder="仅用于生成脱敏摘要，不会在审计历史中展示原文"
                />
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button type="button" variant="terra" size="sm" disabled={busy || pending != null} onClick={() => beginReview("reject")}>
                    确认拒绝
                  </Button>
                  <Button type="button" variant="ghost" size="sm" disabled={busy || pending != null} onClick={() => setShowReject(false)}>
                    取消
                  </Button>
                </div>
              </div>
            )}
            {pending && !busy && (
              <div className="mt-3 flex min-w-0 flex-col gap-2 border border-amber-200 bg-amber-50 p-3 sm:flex-row sm:items-center sm:justify-between">
                <p className="min-w-0 text-xs text-amber-800">请求结果未知，只能使用原请求重试。</p>
                <Button type="button" variant="outline" size="sm" onClick={retryPending}>
                  重试{pending.decision === "approve" ? "批准" : "拒绝"}
                </Button>
              </div>
            )}
            {busy && <p className="mt-3 inline-flex items-center gap-2 text-xs text-stone-500"><Loader2 className="h-4 w-4 animate-spin" />正在提交商业审核</p>}
            {error && <p role="alert" className="mt-3 flex min-w-0 items-start gap-2 break-words border border-red-200 bg-red-50 p-3 text-xs text-red-700"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}</p>}
            {message && <p role="status" className="mt-3 border border-sage-200 bg-sage-50 p-3 text-xs text-sage-700">{message}</p>}
          </div>

          <div className="pt-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h3 className="inline-flex items-center gap-2 text-sm font-semibold text-stone-800">
                <History className="h-4 w-4" />审计时间线
              </h3>
              <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={() => void loadAudit()}>
                刷新
              </Button>
            </div>
            {loading ? (
              <p className="py-6 text-center text-sm text-stone-400">正在读取审计记录</p>
            ) : (
              <ProductAuditTimeline events={events} />
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
