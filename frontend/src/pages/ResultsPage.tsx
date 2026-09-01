import { useEffect, useMemo, useState } from "react";
import { useDesignStore } from "@/store/useDesignStore";
import { useRequirementStore } from "@/store/useRequirementStore";
import { generateDesigns, restoreCurrentDesigns } from "@/api/designApi";
import DesignCard from "@/components/design/DesignCard";
import LoadingAI from "@/components/chat/LoadingAI";
import StudioPage from "@/components/layout/StudioPage";

const filters = ["综合推荐", "预算最低", "收纳最强", "风格最匹配", "环保优先"] as const;
type Filter = (typeof filters)[number];

export default function ResultsPage() {
  const { generatedPlans, setGeneratedPlans } = useDesignStore();
  const requirement = useRequirementStore((s) => s.requirement);
  const [loading, setLoading] = useState(generatedPlans.length === 0);
  const [filter, setFilter] = useState<Filter>("综合推荐");

  useEffect(() => {
    if (generatedPlans.length > 0) return;
    let cancelled = false;
    void (async () => {
      try {
        const restoredPlans = await restoreCurrentDesigns();
        if (cancelled) return;
        if (restoredPlans?.length) {
          setGeneratedPlans(restoredPlans);
          setLoading(false);
          return;
        }

        const generated = await generateDesigns(requirement);
        if (cancelled) return;
        setGeneratedPlans(generated);
      } catch (error) {
        console.warn("[ResultsPage] 历史方案恢复失败，尝试生成可用方案", error);
        const generated = await generateDesigns(requirement);
        if (cancelled) return;
        setGeneratedPlans(generated);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sortedPlans = useMemo(() => {
    const plans = [...generatedPlans];
    switch (filter) {
      case "预算最低":
        return plans.sort((a, b) => a.budget - b.budget);
      case "收纳最强":
        return plans.sort(
          (a, b) =>
            Number(b.tags.some((t) => t.includes("收纳"))) -
            Number(a.tags.some((t) => t.includes("收纳"))),
        );
      case "风格最匹配":
        return plans.sort((a, b) => b.score - a.score);
      case "环保优先":
        return plans.sort(
          (a, b) =>
            Number(b.materials.some((m) => m.name.includes("木") || m.name.includes("棉麻"))) -
            Number(a.materials.some((m) => m.name.includes("木") || m.name.includes("棉麻"))),
        );
      default:
        return plans.sort((a, b) => b.score - a.score);
    }
  }, [generatedPlans, filter]);

  if (loading) {
    return (
      <StudioPage title="正在并行推演空间方案。" description="AI 正在比较布局、材质、家具与预算组合，并验证每套方案与你的需求匹配程度。">
        <div className="rounded-[2rem] border border-[#1d241f]/15 bg-[#f4f1e9] p-8 shadow-[0_30px_80px_rgb(20_28_22/.12)]"><LoadingAI /></div>
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
