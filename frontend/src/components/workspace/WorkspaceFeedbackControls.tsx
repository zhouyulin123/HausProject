import { CheckCircle2, Loader2, RefreshCw, Send, Star } from "lucide-react";
import type { FeedbackDelivery } from "@/types/feedback";

export default function WorkspaceFeedbackControls({
  planVersionId,
  satisfaction,
  delivery,
  onSatisfactionChange,
  onConfirm,
  onRetry,
}: {
  planVersionId: number | null;
  satisfaction: 1 | 2 | 3 | 4 | 5 | null;
  delivery: FeedbackDelivery | null;
  onSatisfactionChange: (score: 1 | 2 | 3 | 4 | 5 | null) => void;
  onConfirm: () => void;
  onRetry: (delivery: FeedbackDelivery) => void;
}) {
  const confirming = delivery?.request.action_type === "final_select"
    && delivery.status === "sending";
  const confirmed = delivery?.request.action_type === "final_select"
    && delivery.status === "sent"
    && delivery.request.plan_version_id === planVersionId
    && (delivery.request.satisfaction_score ?? null) === satisfaction;

  return (
    <section
      aria-label="方案确认与结构化反馈"
      className="mb-3 flex flex-wrap items-end justify-between gap-3 border border-[#293229] bg-[#171e18] px-4 py-3"
    >
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[9px] tracking-[0.14em] text-[#778278] uppercase">Plan feedback</p>
        <p className="mt-1 text-xs text-[#aeb7af]">
          {planVersionId
            ? `方案版本 ${planVersionId} · 仅提交结构化选择`
            : "生成服务端方案后可确认"}
        </p>
        {delivery && (
          <div
            role={delivery.status === "failed" ? "alert" : "status"}
            className={`mt-2 flex flex-wrap items-center gap-2 text-[10px] ${
              delivery.status === "failed"
                ? "text-[#f1b59e]"
                : delivery.status === "sent"
                  ? "text-[#d5ff67]"
                  : "text-[#f0d39e]"
            }`}
          >
            <span>{delivery.message}</span>
            {delivery.status === "failed" && (
              <button
                type="button"
                onClick={() => onRetry(delivery)}
                className="inline-flex min-h-7 items-center gap-1 border border-current px-2"
              >
                <RefreshCw className="h-3 w-3" /> 重试同步
              </button>
            )}
          </div>
        )}
      </div>

      <div className="flex w-full flex-wrap items-end gap-2 sm:w-auto sm:flex-nowrap">
        <label className="min-w-[132px] flex-1 text-[10px] text-[#89948b] sm:flex-none">
          <span className="mb-1 block">满意度（可选）</span>
          <span className="flex min-h-9 items-center gap-2 border border-white/15 bg-[#111713] px-2">
            <Star className="h-3.5 w-3.5 shrink-0 text-[#f1c08b]" />
            <select
              aria-label="满意度（可选）"
              disabled={!planVersionId || confirming}
              value={satisfaction ?? ""}
              onChange={(event) => {
                const value = Number(event.target.value);
                onSatisfactionChange(
                  value >= 1 && value <= 5 ? value as 1 | 2 | 3 | 4 | 5 : null,
                );
              }}
              className="min-w-0 flex-1 bg-transparent text-xs text-[#e4e8e1] outline-none disabled:opacity-50"
            >
              <option value="">不评分</option>
              {[1, 2, 3, 4, 5].map((score) => (
                <option key={score} value={score}>{score} 分</option>
              ))}
            </select>
          </span>
        </label>
        <button
          type="button"
          disabled={!planVersionId || confirming}
          onClick={onConfirm}
          className="flex min-h-9 flex-1 items-center justify-center gap-2 bg-[#d5ff67] px-3 text-xs font-semibold text-[#111713] transition-colors hover:bg-[#e0ff91] disabled:cursor-not-allowed disabled:opacity-45 sm:flex-none"
        >
          {confirming
            ? <Loader2 className="h-4 w-4 animate-spin" />
            : confirmed
              ? <CheckCircle2 className="h-4 w-4" />
              : <Send className="h-4 w-4" />}
          {confirming ? "正在确认" : confirmed ? "已确认当前方案" : "确认当前方案"}
        </button>
      </div>
    </section>
  );
}
