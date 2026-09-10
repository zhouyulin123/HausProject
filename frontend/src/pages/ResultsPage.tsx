import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useDesignStore } from "@/store/useDesignStore";
import { useRequirementStore } from "@/store/useRequirementStore";
import { generateDesigns, restoreCurrentDesigns } from "@/api/designApi";
import DesignCard from "@/components/design/DesignCard";
import LoadingAI from "@/components/chat/LoadingAI";
import StudioPage from "@/components/layout/StudioPage";
import type { DesignPlan } from "@/types/design";
import type { UserRequirement } from "@/types/requirement";

const filters = ["方案顺序", "预算最低", "收纳优先", "环保材料优先"] as const;
type Filter = (typeof filters)[number];

export async function loadResultsPlans(
  requirement: UserRequirement,
  isCancelled: () => boolean,
): Promise<DesignPlan[] | undefined> {
  const restoredPlans = await restoreCurrentDesigns();
  if (isCancelled()) return undefined;
  if (restoredPlans !== null) return restoredPlans;

  const generatedPlans = await generateDesigns(requirement);
  return isCancelled() ? undefined : generatedPlans;
}

export function ResultsLoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-4 rounded-[2rem] border border-[#8f4938] bg-[#2b1c18] p-6 text-[#f1b59e] shadow-[0_30px_80px_rgb(20_28_22/.12)] sm:flex-row sm:items-center"
    >
      <AlertTriangle className="h-6 w-6 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">历史方案恢复失败</p>
        <p className="mt-1 text-xs leading-5 text-[#d7aaa1]">
          当前未能确认是否已有设计任务，因此不会自动创建新任务。请恢复连接后重试。
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 border border-current px-4 text-xs font-semibold"
      >
        <RefreshCw className="h-4 w-4" />
        重新恢复
      </button>
    </div>
  );
}

export default function ResultsPage() {
  const { generatedPlans, setGeneratedPlans } = useDesignStore();
  const requirement = useRequirementStore((s) => s.requirement);
  const [loading, setLoading] = useState(generatedPlans.length === 0);
  const [filter, setFilter] = useState<Filter>("方案顺序");
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    if (generatedPlans.length > 0) return;
    let cancelled = false;
    setLoadError(false);
    void (async () => {
      try {
        const plans = await loadResultsPlans(requirement, () => cancelled);
        if (plans !== undefined) setGeneratedPlans(plans);
      } catch {
        if (!cancelled) setLoadError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadAttempt]);

  const sortedPlans = useMemo(() => {
    const plans = [...generatedPlans];
    switch (filter) {
      case "预算最低":
        return plans.sort((a, b) => a.budget - b.budget);
      case "收纳优先":
        return plans.sort(
          (a, b) =>
            Number(b.tags.some((t) => t.includes("收纳"))) -
            Number(a.tags.some((t) => t.includes("收纳"))),
        );
      case "环保材料优先":
        return plans.sort(
          (a, b) =>
            Number(b.materials.some((m) => m.name.includes("木") || m.name.includes("棉麻"))) -
            Number(a.materials.some((m) => m.name.includes("木") || m.name.includes("棉麻"))),
        );
      default:
        return plans;
    }
  }, [generatedPlans, filter]);

  if (loading) {
    return (
      <StudioPage title="正在并行推演空间方案。" description="AI 正在比较布局、材质、家具与预算组合，并验证每套方案与你的需求匹配程度。">
        <div className="rounded-[2rem] border border-[#1d241f]/15 bg-[#f4f1e9] p-8 shadow-[0_30px_80px_rgb(20_28_22/.12)]"><LoadingAI /></div>
      </StudioPage>
    );
  }

  if (loadError) {
    return (
      <StudioPage
        title="暂时无法恢复设计结果。"
        description="我们会保留当前需求，不会在恢复状态未知时重复创建任务。"
      >
        <ResultsLoadError
          onRetry={() => {
            setLoading(true);
            setLoadError(false);
            setLoadAttempt((current) => current + 1);
          }}
        />
      </StudioPage>
    );
  }

  return (
    <StudioPage title={`已完成 ${sortedPlans.length} 套空间提案。`} description="每套方案都基于同一份需求简报，却采用不同的布局和设计策略。你可以比较、保存，或继续让 AI 调整。">
      <div className="rounded-[2rem] border border-[#1d241f]/15 bg-[#f4f1e9] p-5 shadow-[0_30px_80px_rgb(20_28_22/.12)] sm:p-8">
      {/* 筛选项 */}
      <div className="mt-8 flex flex-wrap justify-center gap-2.5">
        {filters.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={`rounded-full px-4 py-2 text-sm font-medium transition-all ${
              filter === f
                ? "bg-sage-600 text-white shadow-card"
                : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400 hover:text-sage-700"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {sortedPlans.map((plan, i) => (
          <DesignCard key={`${filter}-${plan.id}`} plan={plan} index={i} />
        ))}
      </div>
      </div>
    </StudioPage>
  );
}
