import { useCallback, useEffect, useState } from "react";
import { ClipboardList, MessageSquareQuote } from "lucide-react";
import Button from "@/components/common/Button";
import EmptyState from "@/components/common/EmptyState";
import PageTitle from "@/components/common/PageTitle";
import {
  addQuote,
  getOrder,
  listOrderPool,
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

const filters: { label: string; value: OrderStatus | "" }[] = [
  { label: "全部", value: "" },
  { label: "待报价", value: "open" },
  { label: "已有报价", value: "quoted" },
  { label: "已成交", value: "assigned" },
  { label: "已关闭", value: "closed" },
];

export default function WorkspacePage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [status, setStatus] = useState<OrderStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<Order | null>(null);
  const [quotingId, setQuotingId] = useState<number | null>(null);
  const [quotePrice, setQuotePrice] = useState("");
  const [quoteNote, setQuoteNote] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOrders(await listOrderPool(status || undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载订单池失败");
    } finally {
      setLoading(false);
    }
  }, [status]);

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

  const handleQuote = async () => {
    if (!quotingId || !Number(quotePrice)) {
      setError("请输入报价金额");
      return;
    }
    setError("");
    try {
      await addQuote(quotingId, {
        total_price: Number(quotePrice),
        note: quoteNote || undefined,
      });
      setQuotingId(null);
      setQuotePrice("");
      setQuoteNote("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "报价失败");
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <PageTitle
        title="厂家工作台"
        description="订单池中汇聚了客户发布的装修意向，报价后客户会收到通知并选择。"
      />

      <div className="mt-5 flex flex-wrap gap-2">
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setStatus(f.value)}
            className={`rounded-full px-3.5 py-1.5 text-sm transition-colors ${
              status === f.value
                ? "bg-sage-600 text-white"
                : "bg-cream-100 text-stone-600 hover:bg-cream-200"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="mt-6 space-y-3">
        {loading ? (
          <p className="py-10 text-center text-sm text-stone-400">加载中...</p>
        ) : orders.length === 0 ? (
          <EmptyState
            icon={ClipboardList}
            title="订单池为空"
            description="暂无客户发布装修意向。"
          />
        ) : (
          orders.map((order) => (
            <div
              key={order.id}
              className="rounded-2xl border border-cream-200 bg-white p-4"
            >
              <div className="flex items-center justify-between gap-3">
                <button
                  className="min-w-0 flex-1 text-left"
                  onClick={() => void openDetail(order.id)}
                >
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
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                        已有 {order.pending_quote_count} 人报价
                      </span>
                    )}
                  </div>
                  <p className="mt-1 truncate text-xs text-stone-400">
                    {order.order_no} · 客户 {order.customer_name || order.customer_id} ·{" "}
                    {order.created_at}
                  </p>
                </button>
                {(order.status === "open" || order.status === "quoted") && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setQuotingId(order.id);
                      setQuotePrice("");
                      setQuoteNote("");
                    }}
                  >
                    <MessageSquareQuote className="h-4 w-4" />
                    报价
                  </Button>
                )}
              </div>

              {quotingId === order.id && (
                <div className="mt-4 rounded-xl bg-cream-50 p-4">
                  <div className="flex gap-3">
                    <input
                      className={inputClass}
                      type="number"
                      placeholder="报价金额（元）"
                      value={quotePrice}
                      onChange={(e) => setQuotePrice(e.target.value)}
                    />
                    <Button size="sm" onClick={() => void handleQuote()}>
                      提交报价
                    </Button>
                  </div>
                  <textarea
                    className={`${inputClass} mt-2 min-h-20 resize-y`}
                    placeholder="报价说明（选填）"
                    value={quoteNote}
                    onChange={(e) => setQuoteNote(e.target.value)}
                  />
                </div>
              )}

              {expandedId === order.id && detail && (
                <div className="mt-4 border-t border-cream-100 pt-4">
                  {detail.description && (
                    <p className="mb-3 text-sm leading-relaxed text-stone-600">
                      {detail.description}
                    </p>
                  )}
                  {detail.quotes?.length ? (
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
                          </div>
                          <span className="text-xs text-stone-400">
                            {quote.status === "accepted"
                              ? "已成交"
                              : quote.status === "rejected"
                                ? "未选中"
                                : "待客户选择"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-stone-400">暂无报价</p>
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
