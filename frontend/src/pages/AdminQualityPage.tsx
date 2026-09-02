import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  ChartNoAxesColumnIncreasing,
  CircleDollarSign,
  Clock3,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import {
  fetchFailureClusters,
  fetchQualitySummary,
  updateFailureCluster,
} from "@/api/adminApi";
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
  const [verifiedVersion, setVerifiedVersion] = useState(cluster.verified_version ?? "");
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
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              aria-label={`${cluster.code} 复测版本`}
              value={verifiedVersion}
              maxLength={100}
              onChange={(event) => setVerifiedVersion(event.target.value)}
              placeholder="回归复测版本"
              className="min-h-9 min-w-0 flex-1 border border-cream-300 px-3 text-xs outline-none focus:border-sage-500"
            />
            <Button
              size="sm"
              disabled={busy || !verifiedVersion.trim()}
              onClick={() => onUpdate(cluster.id, {
                status: "verified",
                verified_version: verifiedVersion.trim(),
              })}
            >
              <ShieldCheck className="h-4 w-4" /> 验证关闭
            </Button>
          </div>
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
