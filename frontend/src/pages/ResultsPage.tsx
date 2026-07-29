import { useEffect, useMemo, useState } from "react";
import { useDesignStore } from "@/store/useDesignStore";
import { useRequirementStore } from "@/store/useRequirementStore";
import { generateDesigns } from "@/api/designApi";
import DesignCard from "@/components/design/DesignCard";
import LoadingAI from "@/components/chat/LoadingAI";

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
    void generateDesigns(requirement).then((plans) => {
      if (cancelled) return;
      setGeneratedPlans(plans);
      setLoading(false);
    });
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
      <div className="mx-auto max-w-3xl px-4 py-16">
        <LoadingAI />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold sm:text-3xl">
          为你生成了 {sortedPlans.length} 套家装方案
        </h1>
        <p className="mt-2.5 text-sm text-stone-500 sm:text-base">
          根据你的户型、预算、风格偏好和生活习惯智能生成
        </p>
      </div>

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

      <div className="mt-10 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {sortedPlans.map((plan, i) => (
          <DesignCard key={`${filter}-${plan.id}`} plan={plan} index={i} />
        ))}
      </div>
    </div>
  );
}
