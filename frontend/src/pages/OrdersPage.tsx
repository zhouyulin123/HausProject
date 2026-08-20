import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  ClipboardList,
  Plus,
  X,
} from "lucide-react";
import Button from "@/components/common/Button";
import EmptyState from "@/components/common/EmptyState";
import PageTitle from "@/components/common/PageTitle";
import {
  acceptQuote,
  closeOrder,
  createOrder,
  getOrder,
  listMyOrders,
  orderStatusLabel,
  type Order,
  type OrderStatus,
} from "@/api/orderApi";

const inputClass =
  "w-full rounded-xl border border-cream-300 bg-white/80 px-4 py-2.5 text-sm text-stone-700 placeholder:text-stone-300 outline-none transition-colors focus:border-sage-500 focus:ring-2 focus:ring-sage-100";

const statusClass: Record<OrderStatus, string> = {
  open: "bg-amber-100 text-amber-700",
  quoted: "bg-blue-100 text-blue-700",
  assigned: "bg-sage-100 text-sage-700",
  closed: "bg-stone-100 text-stone-500",
  cancelled: "bg-stone-100 text-stone-500",
};

function formatBudget(order: Order): string {
  if (order.budget_min && order.budget_max) {
    return `预算 ¥${order.budget_min.toLocaleString()} - ${order.budget_max.toLocaleString()}`;
  }
  if (order.budget_max) return `预算上限 ¥${order.budget_max.toLocaleString()}`;
  return "预算未指定";
}

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Order | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    title: "",
    description: "",
    budget_min: "",
    budget_max: "",
  });

  const load = useCallback(async () => {
    try {
      setOrders(await listMyOrders());
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载订单失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (orderId: number) => {
    if (expandedId === orderId) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    try {
      setDetail(await getOrder(orderId));
      setExpandedId(orderId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载订单详情失败");
    }
  };

  const handleCreate = async () => {
    setError("");
    try {
      await createOrder({
        source_type: "requirement",
        title: form.title || undefined,
        description: form.description || undefined,
        budget_min: form.budget_min ? Number(form.budget_min) : undefined,
        budget_max: form.budget_max ? Number(form.budget_max) : undefined,
      });
      setForm({ title: "", description: "", budget_min: "", budget_max: "" });
      setShowCreate(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "发布失败");
    }
  };

  const handleAccept = async (orderId: number, quoteId: number) => {
    setError("");
    try {
      await acceptQuote(orderId, quoteId);
      setDetail(await getOrder(orderId));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
  };

  const handleClose = async (orderId: number) => {
    setError("");
    try {
      await closeOrder(orderId);
      setDetail(await getOrder(orderId));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageTitle
        title="我的订单"
        description="发布装修意向，厂家会在订单池中看到并为你报价，对比后选择心仪的报价成交。"
        extra={
          <Button onClick={() => setShowCreate((v) => !v)}>
            <Plus className="h-4 w-4" />
            发布订单意向
          </Button>
        }
      />

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      {showCreate && (
        <div className="mt-6 rounded-2xl border border-cream-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">发布订单意向</h2>
            <button onClick={() => setShowCreate(false)} aria-label="关闭">
              <X className="h-4 w-4 text-stone-400" />
            </button>
          </div>
          <div className="mt-4 grid gap-3">
            <input
              className={inputClass}
              placeholder="标题（如：全屋定制，奶油风）"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
            <textarea
              className={`${inputClass} min-h-24 resize-y`}
              placeholder="描述你的装修需求、空间、预算等"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <div className="grid grid-cols-2 gap-3">
              <input
                className={inputClass}
                type="number"
                placeholder="预算下限（元）"
                value={form.budget_min}
                onChange={(e) => setForm({ ...form, budget_min: e.target.value })}
              />
              <input
                className={inputClass}
                type="number"
                placeholder="预算上限（元）"
                value={form.budget_max}
                onChange={(e) => setForm({ ...form, budget_max: e.target.value })}
              />
            </div>
            <Button onClick={() => void handleCreate()}>发布</Button>
          </div>
        </div>
      )}

      <div className="mt-6 space-y-3">
        {loading ? (
          <p className="py-10 text-center text-sm text-stone-400">加载中...</p>
        ) : orders.length === 0 ? (
          <EmptyState
            icon={ClipboardList}
            title="还没有订单意向"
            description="发布一条装修意向，让厂家为你报价。"
            action={
              <Button onClick={() => setShowCreate(true)}>发布订单意向</Button>
            }
          />
        ) : (
          orders.map((order) => (
            <div
              key={order.id}
              className="rounded-2xl border border-cream-200 bg-white p-4"
            >
              <button
                className="flex w-full items-center justify-between gap-3 text-left"
                onClick={() => void openDetail(order.id)}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-stone-800">
                      {order.title || order.order_no}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${statusClass[order.status]}`}
                    >
                      {orderStatusLabel[order.status]}
                    </span>
                    {(order.pending_quote_count ?? 0) > 0 && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                        {order.pending_quote_count} 个报价待选择
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-xs text-stone-400">
                    {order.order_no} · {formatBudget(order)} ·{" "}
                    {order.created_at}
                  </p>
                </div>
              </button>

              {expandedId === order.id && detail && (
                <div className="mt-4 border-t border-cream-100 pt-4">
                  {detail.description && (
                    <p className="mb-3 text-sm leading-relaxed text-stone-600">
                      {detail.description}
                    </p>
                  )}

                  {!detail.quotes?.length ? (
                    <p className="text-sm text-stone-400">暂无厂家报价</p>
                  ) : (
                    <ul className="space-y-2">
                      {detail.quotes.map((quote) => (
                        <li
                          key={quote.id}
                          className="flex items-center justify-between rounded-xl bg-cream-50 px-4 py-3"
                        >
                          <div>
                            <p className="text-sm font-medium text-stone-800">
                              {quote.factory_name || `厂家 ${quote.factory_id}`}
                              <span className="ml-2 text-stone-400">
                                ¥{quote.total_price.toLocaleString()}
                              </span>
                            </p>
                            {quote.note && (
                              <p className="mt-0.5 text-xs text-stone-500">
                                {quote.note}
                              </p>
                            )}
                            {quote.status === "accepted" && (
                              <span className="mt-1 inline-flex items-center gap-1 text-xs text-sage-700">
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                已成交
                              </span>
                            )}
                          </div>
                          {quote.status === "pending" &&
                            (order.status === "open" || order.status === "quoted") && (
                              <Button
                                size="sm"
                                onClick={() => void handleAccept(order.id, quote.id)}
                              >
                                选择此报价
                              </Button>
                            )}
                        </li>
                      ))}
                    </ul>
                  )}

                  {(order.status === "open" || order.status === "quoted") && (
                    <button
                      className="mt-3 text-xs text-stone-400 hover:text-stone-600"
                      onClick={() => void handleClose(order.id)}
                    >
                      关闭订单
                    </button>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
