import {
  Activity,
  CircleDollarSign,
  Clock3,
  RotateCcw,
  Wrench,
} from "lucide-react";
import type { DesignProjectStatus } from "@/lib/designProject";
import type { AgentExecutionState, AgentExitReason } from "@/types/agent";
import type {
  TaskTimelineBillingStatus,
  TaskTimelineResponse,
  TaskTimelineSource,
} from "@/api/designApi";

const NODE_LABELS: Record<string, string> = {
  idle: "等待开始",
  validate_facts: "校验需求事实",
  request_clarification: "等待补充信息",
  retrieve_catalog: "商品检索",
  plan_design: "生成设计方案",
  verify_plan: "校验方案",
  replan_or_escalate: "重规划或转人工",
  generate_design: "生成设计方案",
  scene_command: "调整 3D 场景",
  custom_furniture: "生成定制家具预览",
};

const EXIT_LABELS: Partial<Record<AgentExitReason, string>> = {
  goal_completed: "任务已完成",
  missing_facts: "等待补充信息",
  invalid_facts: "事实校验未通过",
  approval_required: "等待人工确认",
  timeout: "执行已超时",
  retry_exhausted: "重试已用尽，转人工处理",
  safety_blocked: "安全门禁已阻止执行",
  tool_failed: "工具执行失败",
  generation_queued: "后台生成已排队",
  generation_failed: "后台生成失败，转人工处理",
  cancelled: "任务已取消",
};

function readableNode(node: string): string {
  return NODE_LABELS[node] ?? node.replace(/_/g, " ");
}

function formatMoney(value: number): string {
  return `¥${value.toFixed(2)}`;
}

function formatDeadline(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

const SOURCE_LABELS: Record<TaskTimelineSource, string> = {
  agent: "智能体",
  requirement: "需求解析",
  vision: "空间识别",
  profile: "用户画像",
  generation: "方案生成",
  effect: "效果图",
  blender: "3D 渲染",
};

const BILLING_LABELS: Record<TaskTimelineBillingStatus, string> = {
  metered: "已计费",
  not_billable: "不计费",
  unknown: "计费未知",
};

function formatEventTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export default function AgentExecutionPanel({
  status,
  exitReason,
  execution,
  timeline = null,
  timelineLoading = false,
  onLoadMore,
}: {
  status: DesignProjectStatus;
  exitReason: AgentExitReason | null;
  execution: AgentExecutionState;
  timeline?: TaskTimelineResponse | null;
  timelineLoading?: boolean;
  onLoadMore?: () => void;
}) {
  const deadline = formatDeadline(
    execution.turnExecutionDeadlineAt ?? execution.executionDeadlineAt,
  );
  const fallbackEvents = [...execution.events]
    .sort((left, right) => left.sequence - right.sequence);
  const knownCost = timeline ? timeline.known_cost_cny : execution.costCny;

  return (
    <section
      aria-label="Agent 执行状态"
      className="mb-3 border border-[#293229] bg-[#171e18] px-4 py-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[9px] tracking-[0.14em] text-[#778278] uppercase">
            Agent execution
          </p>
          <p className="mt-1 flex items-center gap-2 text-sm font-medium text-[#edf0e9]">
            <Activity className="h-4 w-4 shrink-0 text-[#d5ff67]" />
            {readableNode(execution.currentNode)}
          </p>
        </div>
        <span className="border border-white/12 px-2 py-1 font-mono text-[9px] text-[#9ba69c]">
          {status.toUpperCase()}
        </span>
      </div>

      <dl className="mt-3 grid gap-px overflow-hidden border border-white/10 bg-white/10 sm:grid-cols-2 xl:grid-cols-4">
        <div className="bg-[#131a15] px-3 py-2.5">
          <dt className="flex items-center gap-1.5 text-[9px] text-[#778278]"><Activity className="h-3 w-3" />执行进度</dt>
          <dd className="mt-1 text-xs text-[#dce1da]">步骤 {execution.stepCount} / {execution.maxSteps}</dd>
        </div>
        <div className="bg-[#131a15] px-3 py-2.5">
          <dt className="flex items-center gap-1.5 text-[9px] text-[#778278]"><RotateCcw className="h-3 w-3" />重规划</dt>
          <dd className="mt-1 text-xs text-[#dce1da]">重试 {execution.retryCount} / {execution.maxRetries}</dd>
        </div>
        <div className="bg-[#131a15] px-3 py-2.5">
          <dt className="flex items-center gap-1.5 text-[9px] text-[#778278]"><CircleDollarSign className="h-3 w-3" />成本</dt>
          <dd className="mt-1 text-xs text-[#dce1da]">
            {knownCost === null
              ? timeline ? "尚无已知成本" : "尚无已结算成本"
              : formatMoney(knownCost)}
          </dd>
          {timeline?.has_unknown_cost && (
            <dd className="mt-1 text-[9px] text-[#f1c08b]">
              另有 {timeline.unknown_cost_event_count} 项未知成本
            </dd>
          )}
          {(execution.costReservedCny > 0 || execution.costLimitCny !== null) && (
            <dd className="mt-1 text-[9px] text-[#778278]">
              {execution.costReservedCny > 0 && `预留 ${formatMoney(execution.costReservedCny)}`}
              {execution.costReservedCny > 0 && execution.costLimitCny !== null && " · "}
              {execution.costLimitCny !== null && `上限 ${formatMoney(execution.costLimitCny)}`}
            </dd>
          )}
        </div>
        <div className="bg-[#131a15] px-3 py-2.5">
          <dt className="flex items-center gap-1.5 text-[9px] text-[#778278]"><Clock3 className="h-3 w-3" />时间边界</dt>
          <dd className="mt-1 text-xs text-[#dce1da]">
            {deadline
              ? `${execution.turnExecutionDeadlineAt ? "本轮截止" : "任务截止"} ${deadline}`
              : "未设置截止时间"}
          </dd>
        </div>
      </dl>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(220px,auto)]">
        <div className="min-w-0">
          <details open>
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[9px] text-[#778278]">
              <Wrench className="h-3 w-3" />任务时间线
            </summary>
            {timeline ? (
              timeline.events.length ? (
                <ol className="mt-1.5 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
                  {timeline.events.map((event) => (
                    <li
                      key={event.event_id}
                      data-event-id={event.event_id}
                      className="min-w-0 border-l border-white/10 pl-2 text-[10px] text-[#aeb7af]"
                    >
                      <span className="mr-1.5 text-[#d5ff67]">{SOURCE_LABELS[event.source_type]}</span>
                      <span>{event.summary}</span>
                      <span className="ml-1.5 font-mono text-[9px] text-[#6f7a71]">
                        {BILLING_LABELS[event.billing_status]}
                        {event.attempt !== null ? ` · 第 ${event.attempt} 次` : ""}
                        {` · ${formatEventTime(event.occurred_at)}`}
                        {event.request_id && (
                          <span title={event.request_id}>{` · 追踪 ${event.request_id.slice(0, 8)}`}</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="mt-1.5 text-[10px] text-[#6f7a71]">暂无统一任务事件</p>
              )
            ) : fallbackEvents.length ? (
              <ol className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1.5">
                {fallbackEvents.map((event) => (
                <li
                  key={event.event_id ?? `${event.turn_id ?? "turn"}-${event.sequence}-${event.type}-${event.node}-${event.created_at ?? "time"}`}
                  data-event-id={event.event_id}
                  className="min-w-0 text-[10px] text-[#aeb7af]"
                >
                  <span className="mr-1.5 font-mono text-[#6f7a71]">{String(event.sequence).padStart(2, "0")}</span>
                  {event.summary || readableNode(event.node)}
                </li>
                ))}
              </ol>
            ) : (
              <p className="mt-1.5 text-[10px] text-[#6f7a71]">暂无工具执行记录</p>
            )}
            <div className="mt-2 flex items-center gap-3">
              {timelineLoading && <span className="text-[9px] text-[#778278]">正在加载时间线</span>}
              {timeline?.next_before_id != null && onLoadMore && (
                <button
                  type="button"
                  onClick={onLoadMore}
                  disabled={timelineLoading}
                  className="text-[9px] text-[#d5ff67] disabled:text-[#6f7a71]"
                >
                  加载更多
                </button>
              )}
            </div>
          </details>
        </div>
        <div className="lg:text-right">
          <p className="text-[9px] text-[#778278]">退出原因</p>
          <p className="mt-1.5 text-[10px] text-[#aeb7af]">
            {exitReason ? EXIT_LABELS[exitReason] ?? exitReason : "任务仍在执行或等待输入"}
          </p>
          {execution.cancelRequestedAt && (
            <p className="mt-1 text-[10px] text-[#f1c08b]">已请求取消，等待当前工具安全退出</p>
          )}
          {execution.hardErrors.length > 0 && (
            <p className="mt-1 text-[10px] text-[#f1b59e]">{execution.hardErrors.length} 项硬校验未通过</p>
          )}
        </div>
      </div>
    </section>
  );
}
