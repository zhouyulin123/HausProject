import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { BookmarkCheck, BookmarkPlus, MessageCircleMore, Sparkles } from "lucide-react";
import type { DesignPlan } from "@/types/design";
import { useDesignStore } from "@/store/useDesignStore";
import { useRequirementStore } from "@/store/useRequirementStore";
import Tag from "@/components/common/Tag";
import Button from "@/components/common/Button";

export default function DesignCard({ plan, index = 0 }: { plan: DesignPlan; index?: number }) {
  const navigate = useNavigate();
  const { savedDesigns, saveDesign } = useDesignStore();
  const rooms = useRequirementStore((s) => s.requirement.rooms);
  const saved = savedDesigns.some((d) => d.planId === plan.id);

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: index * 0.1 }}
      className="group flex flex-col overflow-hidden rounded-3xl border border-cream-200 bg-white/80 transition-all duration-300 hover:-translate-y-1.5 hover:shadow-lift"
    >
      {/* 封面占位 */}
      <Link to={`/design/${plan.id}`} className={`relative block h-44 ${plan.coverGradient}`}>
        <span className="absolute top-3 left-3 inline-flex items-center gap-1 rounded-full bg-white/85 px-2.5 py-1 text-xs font-semibold text-sage-700 backdrop-blur">
          <Sparkles className="h-3 w-3" />
          AI 推荐指数 {plan.score}%
        </span>
        <span className="absolute bottom-3 left-4 font-display text-lg font-semibold text-white drop-shadow-sm">
          {plan.style}
        </span>
      </Link>

      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-display text-lg font-semibold text-stone-800">{plan.name}</h3>
          <span className="shrink-0 font-display text-base font-semibold text-terra-600">
            ¥{plan.budget.toLocaleString()}
          </span>
        </div>
        <p className="mt-1 text-xs text-stone-400">适合：{plan.suitableFor.join(" / ")}</p>
        <p className="mt-2.5 line-clamp-2 text-sm leading-relaxed text-stone-500">
          {plan.description}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {plan.tags.map((tag) => (
            <Tag key={tag} tone="wood">
              {tag}
            </Tag>
          ))}
        </div>

        <div className="mt-auto flex gap-2 pt-5">
          <Link to={`/design/${plan.id}`} className="flex-1">
            <Button className="w-full" size="sm">
              查看详情
            </Button>
          </Link>
          <Button
            variant={saved ? "secondary" : "outline"}
            size="sm"
            onClick={() => saveDesign(plan, rooms)}
            title={saved ? "已保存到我的方案" : "保存方案"}
          >
            {saved ? (
              <BookmarkCheck className="h-4 w-4 text-sage-600" />
            ) : (
              <BookmarkPlus className="h-4 w-4" />
            )}
            {saved ? "已保存" : "保存"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/chat")}
            title="继续和 AI 优化这套方案"
          >
            <MessageCircleMore className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
