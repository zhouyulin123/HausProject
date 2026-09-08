import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  ChartNoAxesColumnIncreasing,
  CircleDollarSign,
  Clock3,
  FileUp,
  Loader2,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import {
  AdminApiError,
  fetchFailureClusters,
  fetchQualitySummary,
  fetchRealWorldReadiness,
  importFailureTriageReportFile,
  importFailureVerificationReportFile,
  updateFailureCluster,
} from "@/api/adminApi";
import type { RealWorldReadiness, RealWorldSplit } from "@/api/adminApi";
import Button from "@/components/common/Button";
import EmptyState from "@/components/common/EmptyState";
import PageTitle from "@/components/common/PageTitle";
import {
  QUALITY_WINDOWS,
  buildFailureCodeRows,
  formatDuration,
  formatRate,
  hasQualitySamples,
} from "@/lib/qualityMetrics";
import type {
  FailureCluster,
  FailureClusterListResponse,
  FailureClusterUpdate,
  FailureSeverity,
  FailureStatus,
  QualitySummary,
  QualityWindowDays,
  QualityRenderQueueMetrics,
} from "@/types/quality";

const integerFormatter = new Intl.NumberFormat("zh-CN");
const currencyFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
});

const STATUS_LABELS: Record<FailureStatus, string> = {
  open: "待认领",
  in_progress: "修复中",
  resolved: "待回归验证",
  verified: "已验证关闭",
};
const SEVERITY_LABELS: Record<FailureSeverity, string> = {
  low: "低",
  medium: "中",
  high: "高",
  critical: "严重",
};

const REAL_WORLD_SPLIT_LABELS: Record<RealWorldSplit, string> = {
  development: "开发集",
  regression: "回归集",
  blind: "盲测集",
};

const REAL_WORLD_BLOCKER_LABELS: Record<string, string> = {
  consent_not_granted: "未取得授权",
  consent_expired: "授权已过期",
  annotation_not_ready: "人工标注未就绪",
  purpose_not_allowed: "使用目的不在授权范围",
  split_not_assigned: "未分配评测分组",
  duplicate_case: "案例重复",
  case_not_private_real: "不是真实私有案例",
  trusted_schema_required: "清单版本不支持可信证据",
  synthetic_release_case: "发布分组混入合成案例",
};

export function failureTriageImportErrorMessage(error: unknown): string {
  if (error instanceof AdminApiError && error.status === 409) {
    return "报告与已导入记录冲突，请核对报告版本和签名";
  }
  if (error instanceof AdminApiError && error.status === 422) {
    return "报告验签失败，未导入任何数据";
  }
  if (error instanceof AdminApiError && error.status === 503) {
    return "服务端验签尚未配置，报告未导入";
  }
  if (error instanceof Error && error.message === "报告 JSON 解析失败") {
    return "报告 JSON 解析失败，请选择有效的 JSON 文件";
  }
  return error instanceof Error ? error.message : "失败分诊报告导入失败";
}

export function FailureTriageImportControl({
  importing,
  error,
  success,
  onFile,
}: {
  importing: boolean;
  error: string;
  success: string;
  onFile: (file: File) => void;
}) {
  return (
    <section className="mt-9 border-t border-cream-300 pt-7" aria-label="导入失败分诊报告">
      <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-sm font-semibold text-stone-700">失败分诊报告</h2>
          <p className="mt-1 text-xs text-stone-400">导入评测流程生成并签名的 JSON 报告</p>
        </div>
        <label className={`inline-flex min-h-9 items-center justify-center gap-2 border border-stone-300 bg-white/70 px-3 text-sm font-medium text-stone-700 transition-colors hover:border-sage-500 hover:text-sage-700 ${importing ? "pointer-events-none opacity-50" : "cursor-pointer"}`}>
          {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileUp className="h-4 w-4" />}
          {importing ? "正在导入" : "导入签名报告"}
          <input
            type="file"
            accept="application/json,.json"
            className="sr-only"
            disabled={importing}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) onFile(file);
            }}
          />
        </label>
      </div>
      {error && <p role="alert" className="mt-3 border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">{error}</p>}
      {success && <p role="status" className="mt-3 border border-sage-200 bg-sage-50 px-4 py-3 text-xs text-sage-700">{success}</p>}
    </section>
  );
}

export function failureVerificationImportErrorMessage(error: unknown): string {
  if (error instanceof AdminApiError && error.status === 409) {
    return "复测证明与已导入记录冲突，请核对证明版本";
  }
  if (error instanceof AdminApiError && error.status === 422) {
    return "复测证明验签失败，未更新任何失败簇";
  }
  if (error instanceof AdminApiError && error.status === 503) {
    return "服务端复测证明验签尚未配置，未更新失败簇";
  }
  if (error instanceof Error && error.message === "复测证明 JSON 解析失败") {
    return "复测证明 JSON 解析失败，请选择有效的 JSON 文件";
  }
  return error instanceof Error ? error.message : "签名复测证明导入失败";
}

export function FailureVerificationImportControl({
  importing,
  error,
  success,
  onFile,
}: {
  importing: boolean;
  error: string;
  success: string;
  onFile: (file: File) => void;
}) {
  return (
    <section className="mt-6 border-t border-cream-200 pt-6" aria-label="导入签名复测证明">
      <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-sm font-semibold text-stone-700">签名复测证明</h2>
          <p className="mt-1 text-xs text-stone-400">导入受控回归流程生成的 JSON 证明</p>
        </div>
        <label className={`inline-flex min-h-9 items-center justify-center gap-2 border border-stone-300 bg-white/70 px-3 text-sm font-medium text-stone-700 transition-colors hover:border-sage-500 hover:text-sage-700 ${importing ? "pointer-events-none opacity-50" : "cursor-pointer"}`}>
          {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
          {importing ? "正在验证" : "导入签名复测证明"}
          <input
            type="file"
            accept="application/json,.json"
            className="sr-only"
            disabled={importing}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) onFile(file);
            }}
          />
        </label>
      </div>
      {error && <p role="alert" className="mt-3 border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">{error}</p>}
      {success && <p role="status" className="mt-3 border border-sage-200 bg-sage-50 px-4 py-3 text-xs text-sage-700">{success}</p>}
    </section>
  );
}

export function RealWorldReadinessContent({
  data,
  loading,
  error,
  onRetry,
}: {
  data: RealWorldReadiness | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  const blockers = data
    ? Object.entries(data.blocker_counts)
      .filter(([, count]) => count > 0)
      .sort(([, left], [, right]) => right - left)
      .slice(0, 5)
    : [];
  return (
    <section className="mt-9 border-t border-cream-300 pt-7" aria-label="真实案例就绪度">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">真实案例就绪度</h2>
          <p className="mt-1 text-xs text-stone-400">仅展示授权、标注与分组的聚合准入结果</p>
        </div>
        <Button variant="outline" size="sm" disabled={loading} onClick={onRetry}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> 刷新
        </Button>
      </div>

      {loading && !data ? (
        <div className="mt-4 h-32 animate-pulse border-y border-cream-200 bg-white/70" />
      ) : error ? (
        <div role="alert" className="mt-4 flex flex-col items-start gap-3 border border-red-200 bg-red-50 p-4 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 shrink-0" />{error}</span>
          <button type="button" className="font-medium underline" onClick={onRetry}>重试</button>
        </div>
      ) : data ? (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <div className="border border-cream-200 bg-white/80 p-4 sm:col-span-2">
              <p className="text-xs text-stone-400">发布门槛</p>
              <p className={`mt-2 text-2xl font-semibold ${data.minimum_met ? "text-sage-700" : "text-terra-700"}`}>
                {data.private_real_eligible_total} / {data.minimum_required}
              </p>
              <p className="mt-1 text-xs text-stone-500">
                {data.minimum_met
                  ? "真实案例数量和三组分配均达到最低要求"
                  : data.private_real_eligible_total < data.minimum_required
                    ? `尚缺 ${data.minimum_required - data.private_real_eligible_total} 例`
                    : "数量已满足，但仍有评测分组无准入案例"}
              </p>
            </div>
            {(Object.entries(REAL_WORLD_SPLIT_LABELS) as Array<[RealWorldSplit, string]>).map(([split, label]) => {
              const counts = data.split_counts[split];
              return (
                <div key={split} className="border border-cream-200 bg-white/80 p-4">
                  <p className="text-xs text-stone-400">{label}</p>
                  <p className="mt-2 text-xl font-semibold text-stone-800">{counts.eligible}</p>
                  <p className="mt-1 text-xs text-stone-500">准入 / 候选 {counts.total}</p>
                </div>
              );
            })}
          </div>
          <div className="mt-4 border-y border-cream-200 bg-white/60 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-stone-500">
              <span>候选 {data.total} · 阻断 {data.blocked_total}</span>
              <span>检查于 {new Date(data.checked_at).toLocaleString("zh-CN", { hour12: false })}</span>
            </div>
            {blockers.length ? (
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2 border-t border-cream-100 pt-3 text-xs text-terra-700">
                {blockers.map(([code, count]) => (
                  <span key={code}>{REAL_WORLD_BLOCKER_LABELS[code] ?? code} <strong>{count}</strong></span>
                ))}
              </div>
            ) : (
              <p className="mt-3 border-t border-cream-100 pt-3 text-xs text-sage-700">当前没有案例准入阻断项</p>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}

function FailureClusterRow({
  cluster,
  busy,
  onUpdate,
}: {
  cluster: FailureCluster;
  busy: boolean;
  onUpdate: (clusterId: number, update: FailureClusterUpdate) => void;
}) {
  const [owner, setOwner] = useState(cluster.owner ?? "");
  const [fixedVersion, setFixedVersion] = useState(cluster.fixed_version ?? "");
  return (
    <article className="border border-cream-200 bg-white p-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <code className="break-all text-xs font-semibold text-stone-700">{cluster.code}</code>
            <span className="border border-terra-200 bg-terra-50 px-1.5 py-0.5 text-[10px] text-terra-700">
              {SEVERITY_LABELS[cluster.severity]}
            </span>
            <span className="border border-sage-200 bg-sage-50 px-1.5 py-0.5 text-[10px] text-sage-700">
              {STATUS_LABELS[cluster.status]}
            </span>
          </div>
          <p className="mt-2 text-xs text-stone-400">
            {cluster.failure_type} · 数据 {cluster.data_version} · 检出 {cluster.detected_version}
          </p>
        </div>
        <div className="shrink-0 text-right text-xs text-stone-500">
          <p>{cluster.occurrence_count} 次出现</p>
          <p className="mt-1">影响 {cluster.affected_count} 个匿名样本</p>
        </div>
      </div>
      <div className="mt-4 border-t border-cream-100 pt-3">
        {cluster.status === "open" && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              aria-label={`${cluster.code} 负责人`}
              value={owner}
              maxLength={100}
              onChange={(event) => setOwner(event.target.value)}
              placeholder="负责人标识"
              className="min-h-9 min-w-0 flex-1 border border-cream-300 px-3 text-xs outline-none focus:border-sage-500"
            />
            <Button
              size="sm"
              disabled={busy || !owner.trim()}
              onClick={() => onUpdate(cluster.id, {
                status: "in_progress",
                owner: owner.trim(),
              })}
            >
              <UserCheck className="h-4 w-4" /> 认领并开始修复
            </Button>
          </div>
        )}
        {cluster.status === "in_progress" && (
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              aria-label={`${cluster.code} 修复版本`}
              value={fixedVersion}
              maxLength={100}
              onChange={(event) => setFixedVersion(event.target.value)}
              placeholder="修复版本"
              className="min-h-9 min-w-0 flex-1 border border-cream-300 px-3 text-xs outline-none focus:border-sage-500"
            />
            <Button
              size="sm"
              disabled={busy || !fixedVersion.trim()}
              onClick={() => onUpdate(cluster.id, {
                status: "resolved",
                fixed_version: fixedVersion.trim(),
              })}
            >
              <Wrench className="h-4 w-4" /> 标记修复
            </Button>
          </div>
        )}
        {cluster.status === "resolved" && (
          <p className="flex items-center gap-2 text-xs text-stone-500">
            <ShieldCheck className="h-4 w-4" />
            等待受控回归证据验证，管理员不能手工关闭
          </p>
        )}
        {cluster.status === "verified" && (
          <p className="flex items-center gap-2 text-xs text-sage-700">
            <ShieldCheck className="h-4 w-4" />
            修复 {cluster.fixed_version} · 复测 {cluster.verified_version}
          </p>
        )}
      </div>
    </article>
  );
}

export function FailureTriageContent({
  data,
  loading,
  error,
  actionError,
  busyClusterId,
  onRefresh,
  onUpdate,
}: {
  data: FailureClusterListResponse | null;
  loading: boolean;
  error: string;
  actionError: string;
  busyClusterId: number | null;
  onRefresh: () => void;
  onUpdate: (clusterId: number, update: FailureClusterUpdate) => void;
}) {
  return (
    <section className="mt-12 border-t border-cream-300 pt-7" aria-label="失败修复闭环">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">失败修复闭环</h2>
          <p className="mt-1 text-xs text-stone-400">匿名聚类 · 认领 · 修复 · 回归验证</p>
        </div>
        <Button variant="outline" size="sm" disabled={loading} onClick={onRefresh}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> 刷新
        </Button>
      </div>
      {(error || actionError) && (
        <div role="alert" className="mt-4 flex flex-wrap items-center justify-between gap-3 border border-red-200 bg-red-50 p-4 text-xs text-red-700">
          <span>{actionError || error}</span>
          {error && (
            <button type="button" className="font-medium underline" onClick={onRefresh}>重试加载</button>
          )}
        </div>
      )}
      {data && (
        <div className="mt-4 flex flex-wrap gap-2 text-[10px] text-stone-500">
          <span className="border border-cream-300 px-2 py-1">总计 {data.summary.total}</span>
          {Object.entries(data.summary.by_severity).map(([severity, count]) => (
            <span key={severity} className="border border-terra-200 px-2 py-1">
              严重度 {SEVERITY_LABELS[severity as FailureSeverity] ?? severity} {count}
            </span>
          ))}
          {Object.entries(data.summary.by_status).map(([status, count]) => (
            <span key={status} className="border border-sage-200 px-2 py-1">
              {STATUS_LABELS[status as FailureStatus] ?? status} {count}
            </span>
          ))}
        </div>
      )}
      {loading && !data ? (
        <div className="mt-4 h-28 animate-pulse border border-cream-200 bg-white/70" />
      ) : data?.items.length === 0 ? (
        <p className="mt-4 border border-dashed border-cream-300 p-5 text-sm text-stone-400">暂无已同步失败簇</p>
      ) : data ? (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {data.items.map((cluster) => (
            <FailureClusterRow
              key={cluster.id}
              cluster={cluster}
              busy={busyClusterId === cluster.id}
              onUpdate={onUpdate}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MetricTile({
  label,
  value,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Activity;
}) {
  return (
    <article className="min-w-0 border border-cream-200 bg-white/80 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium text-stone-500">{label}</p>
        <Icon className="h-4 w-4 shrink-0 text-sage-600" />
      </div>
      <p className="mt-4 break-words font-display text-2xl font-semibold text-stone-800 sm:text-3xl">
        {value}
      </p>
      <p className="mt-2 text-xs leading-5 text-stone-400">{detail}</p>
    </article>
  );
}

function Distribution({
  title,
  codes,
  emptyLabel,
}: {
  title: string;
  codes: Record<string, number>;
  emptyLabel: string;
}) {
  const rows = buildFailureCodeRows(codes);
  const largest = rows[0]?.count ?? 0;
  return (
    <section className="border-t border-cream-200 pt-5">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-sm font-semibold text-stone-700">{title}</h2>
        <span className="font-mono text-[10px] text-stone-400">{rows.length} CODES</span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-4 border border-dashed border-cream-300 px-4 py-5 text-sm text-stone-400">
          {emptyLabel}
        </p>
      ) : (
        <div className="mt-4 divide-y divide-cream-100 border-y border-cream-200">
          {rows.map((row) => (
            <div key={row.code} className="grid grid-cols-[minmax(0,1fr)_minmax(80px,180px)_48px] items-center gap-3 py-3">
              <code className="truncate text-xs text-stone-600" title={row.code}>{row.code}</code>
              <div className="h-1.5 overflow-hidden bg-cream-200">
                <div
                  className="h-full bg-terra-500"
                  style={{ width: `${largest ? (row.count / largest) * 100 : 0}%` }}
                />
              </div>
              <span className="text-right font-mono text-xs text-stone-600">{row.count}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function RenderQueueTile({
  label,
  metrics,
}: {
  label: string;
  metrics: QualityRenderQueueMetrics;
}) {
  return (
    <article className="border border-cream-200 bg-white/80 p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-stone-700">{label}</h2>
        <Activity className="h-4 w-4 text-sage-600" />
      </div>
      <p className="mt-4 text-2xl font-semibold text-stone-800">
        {formatRate(metrics.success_rate)}
      </p>
      <p className="mt-1 text-xs text-stone-400">成功率 · {metrics.completed} 完成 / {metrics.failed + metrics.dead_letter} 失败</p>
      <div className="mt-4 grid grid-cols-2 gap-2 text-xs text-stone-500">
        <span>排队 {metrics.queued}</span>
        <span>执行中 {metrics.running}</span>
        <span>排队 P95 {formatDuration(metrics.queue_wait_p95_ms)}</span>
        <span>执行 P95 {formatDuration(metrics.execution_p95_ms)}</span>
      </div>
    </article>
  );
}

function FeedbackMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="min-w-0 border-l-2 border-sage-200 pl-3">
      <p className="text-xs text-stone-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-stone-800">{value}</p>
      {detail && <p className="mt-1 text-[11px] text-stone-400">{detail}</p>}
    </div>
  );
}

function FeedbackSummary({ summary }: { summary: QualitySummary }) {
  const feedback = summary.feedback;
  const actions = [
    ["采用", feedback.action_counts.adopt],
    ["删除", feedback.action_counts.remove],
    ["替换", feedback.action_counts.replace],
    ["移动", feedback.action_counts.move],
    ["最终选择", feedback.action_counts.final_select],
  ] as const;
  const satisfaction = feedback.satisfaction_mean == null
    ? "--"
    : `${feedback.satisfaction_mean.toFixed(2)} / 5`;
  return (
    <section className="mt-9 border-t border-cream-200 pt-5" aria-label="用户反馈回流">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-stone-700">用户反馈回流</h2>
        <span className="text-xs text-stone-400">{feedback.total} 条匿名动作反馈</span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 border-y border-cream-200 bg-white/60 px-4 py-4 sm:grid-cols-4 lg:grid-cols-7">
        {actions.map(([label, value]) => (
          <FeedbackMetric key={label} label={label} value={integerFormatter.format(value)} />
        ))}
        <FeedbackMetric
          label="修改率"
          value={feedback.modification_rate == null ? "--" : formatRate(feedback.modification_rate)}
          detail={feedback.total > 0 ? `${feedback.modification_total} 次修改` : "暂无动作样本"}
        />
        <FeedbackMetric
          label="满意度"
          value={satisfaction}
          detail={feedback.satisfaction_count > 0 ? `${feedback.satisfaction_count} 份评分` : "暂无评分样本"}
        />
      </div>
    </section>
  );
}

export function QualitySummaryContent({ summary }: { summary: QualitySummary }) {
  const generatedAt = new Date(summary.generated_at).toLocaleString("zh-CN", {
    hour12: false,
  });

  return (
    <>
      <div className="mt-7 flex flex-wrap items-center justify-between gap-2 text-xs text-stone-400">
        <span>统计窗口：最近 {summary.window_days} 天</span>
        <span>更新时间：{generatedAt}</span>
      </div>
      <section className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="生成成功率"
          value={formatRate(summary.generation.success_rate)}
          detail={`${summary.generation.completed} 成功 / ${summary.generation.failed} 失败`}
          icon={Activity}
        />
        <MetricTile
          label="降级率"
          value={formatRate(summary.generation.fallback_rate)}
          detail={`已完成生成 ${summary.generation.completed} 次`}
          icon={RefreshCw}
        />
        <MetricTile
          label="生成耗时 P50"
          value={formatDuration(summary.generation.duration_p50_ms)}
          detail={`P95 ${formatDuration(summary.generation.duration_p95_ms)}`}
          icon={Clock3}
        />
        <MetricTile
          label="Agent 转人工率"
          value={formatRate(summary.agent.handoff_rate)}
          detail={`${summary.agent.handoff_total} 次转人工 / ${summary.agent.turn_total} 轮`}
          icon={Bot}
        />
        <MetricTile
          label="布局硬约束通过率"
          value={formatRate(summary.layout.hard_pass_rate)}
          detail={`${summary.layout.hard_pass_total} 通过 / ${summary.layout.total} 次布局`}
          icon={ShieldCheck}
        />
        <MetricTile
          label="Token 总量"
          value={integerFormatter.format(summary.generation.total_tokens)}
          detail={`${summary.generation.total} 次生成任务`}
          icon={ChartNoAxesColumnIncreasing}
        />
        <MetricTile
          label="推理成本"
          value={currencyFormatter.format(summary.generation.total_cost_cny)}
          detail={
            summary.generation.total_tokens > 0
              ? `每千 Token ${currencyFormatter.format((summary.generation.total_cost_cny / summary.generation.total_tokens) * 1_000)}`
              : "暂无 Token 样本"
          }
          icon={CircleDollarSign}
        />
        <MetricTile
          label="运行中任务"
          value={integerFormatter.format(summary.generation.active)}
          detail={`${summary.generation.cancelled} 已取消 / ${summary.generation.total} 总任务`}
          icon={Activity}
        />
        <MetricTile
          label="GLB 加载失败"
          value={integerFormatter.format(
            summary.feedback.glb_load_failure_total,
          )}
          detail="匿名逐实例事件，不含 URL、用户文本或错误堆栈"
          icon={AlertTriangle}
        />
      </section>

      <FeedbackSummary summary={summary} />

      <section className="mt-9 grid gap-3 lg:grid-cols-2" aria-label="异步渲染队列">
        <RenderQueueTile label="效果图队列" metrics={summary.effect_render} />
        <RenderQueueTile label="Blender 队列" metrics={summary.blender_render} />
      </section>

      <section className="mt-9 border-t border-cream-200 pt-5" aria-label="节点耗时">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-sm font-semibold text-stone-700">节点耗时</h2>
          <span className="font-mono text-[10px] text-stone-400">P50 / P95</span>
        </div>
        {Object.keys(summary.generation.node_latency).length === 0 ? (
          <p className="mt-4 border border-dashed border-cream-300 px-4 py-5 text-sm text-stone-400">当前周期没有节点耗时样本</p>
        ) : (
          <div className="mt-4 divide-y divide-cream-100 border-y border-cream-200">
            {Object.entries(summary.generation.node_latency).map(([node, latency]) => (
              <div key={node} className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-3 text-xs">
                <code className="truncate text-stone-600" title={node}>{node}</code>
                <span className="text-right text-stone-500">{formatDuration(latency.p50_ms)} / {formatDuration(latency.p95_ms)} · {latency.samples} 次</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="mt-9 grid gap-8 lg:grid-cols-2">
        <Distribution title="失败码分布" codes={summary.failure_codes} emptyLabel="当前周期没有验证失败码" />
        <Distribution title="布局问题分布" codes={summary.layout.issue_codes} emptyLabel="当前周期没有布局问题码" />
      </div>
    </>
  );
}

export default function AdminQualityPage() {
  const [windowDays, setWindowDays] = useState<QualityWindowDays>(30);
  const [summary, setSummary] = useState<QualitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [failureClusters, setFailureClusters] = useState<FailureClusterListResponse | null>(null);
  const [failureClustersLoading, setFailureClustersLoading] = useState(true);
  const [failureClustersError, setFailureClustersError] = useState("");
  const [failureActionError, setFailureActionError] = useState("");
  const [busyClusterId, setBusyClusterId] = useState<number | null>(null);
  const [failureReloadKey, setFailureReloadKey] = useState(0);
  const [realWorldReadiness, setRealWorldReadiness] = useState<RealWorldReadiness | null>(null);
  const [realWorldLoading, setRealWorldLoading] = useState(true);
  const [realWorldError, setRealWorldError] = useState("");
  const [realWorldReloadKey, setRealWorldReloadKey] = useState(0);
  const [failureImporting, setFailureImporting] = useState(false);
  const [failureImportError, setFailureImportError] = useState("");
  const [failureImportSuccess, setFailureImportSuccess] = useState("");
  const [verificationImporting, setVerificationImporting] = useState(false);
  const [verificationImportError, setVerificationImportError] = useState("");
  const [verificationImportSuccess, setVerificationImportSuccess] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void fetchQualitySummary(windowDays)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setSummary(null);
        setError(reason instanceof Error ? reason.message : "质量指标加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey, windowDays]);

  const loadFailureClusters = useCallback(async () => {
    setFailureClustersLoading(true);
    setFailureClustersError("");
    setFailureActionError("");
    try {
      setFailureClusters(await fetchFailureClusters());
    } catch (reason) {
      setFailureClustersError(
        reason instanceof Error ? reason.message : "失败簇加载失败",
      );
    } finally {
      setFailureClustersLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadFailureClusters();
  }, [failureReloadKey, loadFailureClusters]);

  useEffect(() => {
    let cancelled = false;
    setRealWorldLoading(true);
    setRealWorldError("");
    void fetchRealWorldReadiness()
      .then((data) => {
        if (!cancelled) setRealWorldReadiness(data);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setRealWorldReadiness(null);
        setRealWorldError(
          reason instanceof Error ? reason.message : "真实案例就绪度加载失败",
        );
      })
      .finally(() => {
        if (!cancelled) setRealWorldLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [realWorldReloadKey]);

  const handleFailureUpdate = useCallback(async (
    clusterId: number,
    update: FailureClusterUpdate,
  ) => {
    setBusyClusterId(clusterId);
    setFailureActionError("");
    try {
      await updateFailureCluster(clusterId, update);
      await loadFailureClusters();
    } catch (reason) {
      setFailureActionError(
        reason instanceof Error ? reason.message : "失败簇更新失败",
      );
    } finally {
      setBusyClusterId(null);
    }
  }, [loadFailureClusters]);

  const handleFailureReportFile = useCallback(async (file: File) => {
    setFailureImporting(true);
    setFailureImportError("");
    setFailureImportSuccess("");
    try {
      const result = await importFailureTriageReportFile(file);
      setFailureImportSuccess(
        result.imported
          ? `已导入 ${result.cluster_count} 个失败簇`
          : "该签名报告已导入，失败簇已刷新",
      );
      await loadFailureClusters();
    } catch (reason) {
      setFailureImportError(failureTriageImportErrorMessage(reason));
    } finally {
      setFailureImporting(false);
    }
  }, [loadFailureClusters]);

  const handleFailureVerificationFile = useCallback(async (file: File) => {
    setVerificationImporting(true);
    setVerificationImportError("");
    setVerificationImportSuccess("");
    try {
      const result = await importFailureVerificationReportFile(file);
      setVerificationImportSuccess(
        result.imported
          ? `已验证关闭 ${result.cluster_count} 个失败簇`
          : "该签名复测证明已导入，失败簇已刷新",
      );
      await loadFailureClusters();
    } catch (reason) {
      setVerificationImportError(failureVerificationImportErrorMessage(reason));
    } finally {
      setVerificationImporting(false);
    }
  }, [loadFailureClusters]);

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-col gap-5 border-b border-cream-300 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <PageTitle
          title="运营质量"
          description="方案生成、智能体编排与布局验证的聚合运行指标。"
        />
        <div className="flex shrink-0 items-center border border-cream-300 bg-white p-1" aria-label="统计周期">
          {QUALITY_WINDOWS.map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => setWindowDays(days)}
              aria-pressed={windowDays === days}
              className={`min-h-9 min-w-14 px-3 text-xs font-medium transition-colors ${
                windowDays === days
                  ? "bg-sage-600 text-white"
                  : "text-stone-500 hover:bg-cream-100 hover:text-stone-700"
              }`}
            >
              {days} 天
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="mt-7 grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="正在加载质量指标">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="h-32 animate-pulse border border-cream-200 bg-white/70" />
          ))}
        </div>
      ) : error ? (
        <div role="alert" className="mt-7 flex flex-col items-start gap-4 border border-red-200 bg-red-50 p-5 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <span>{error}</span>
          </div>
          <Button variant="outline" size="sm" onClick={() => setReloadKey((value) => value + 1)}>
            <RefreshCw className="h-4 w-4" /> 重试
          </Button>
        </div>
      ) : summary && !hasQualitySamples(summary) ? (
        <div className="mt-7">
          <EmptyState
            icon={ChartNoAxesColumnIncreasing}
            title="当前周期暂无运行样本"
            description={`最近 ${windowDays} 天尚未产生可聚合的生成、智能体或布局记录。`}
          />
        </div>
      ) : summary ? <QualitySummaryContent summary={summary} /> : null}
      <RealWorldReadinessContent
        data={realWorldReadiness}
        loading={realWorldLoading}
        error={realWorldError}
        onRetry={() => setRealWorldReloadKey((value) => value + 1)}
      />
      <FailureTriageImportControl
        importing={failureImporting}
        error={failureImportError}
        success={failureImportSuccess}
        onFile={(file) => void handleFailureReportFile(file)}
      />
      <FailureVerificationImportControl
        importing={verificationImporting}
        error={verificationImportError}
        success={verificationImportSuccess}
        onFile={(file) => void handleFailureVerificationFile(file)}
      />
      <FailureTriageContent
        data={failureClusters}
        loading={failureClustersLoading}
        error={failureClustersError}
        actionError={failureActionError}
        busyClusterId={busyClusterId}
        onRefresh={() => setFailureReloadKey((value) => value + 1)}
        onUpdate={(clusterId, update) => void handleFailureUpdate(clusterId, update)}
      />
    </div>
  );
}
