import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Download,
  Eye,
  Heart,
  Home,
  MessageCircleMore,
  Search,
  Trash2,
} from "lucide-react";
import { useDesignStore } from "@/store/useDesignStore";
import type { SavedDesign } from "@/types/design";
import PageTitle from "@/components/common/PageTitle";
import EmptyState from "@/components/common/EmptyState";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";

const filterOptions = [
  "最近创建",
  "已收藏",
  "客厅方案",
  "全屋方案",
  "高预算",
  "低预算",
] as const;
type FilterOption = (typeof filterOptions)[number];

const statusTone: Record<SavedDesign["status"], "cream" | "sage" | "terra" | "wood"> = {
  草稿: "cream",
  已生成: "sage",
  已优化: "terra",
  已导出: "wood",
};

export default function MyDesignsPage() {
  const navigate = useNavigate();
  const {
    savedDesigns,
    removeDesign,
    updateDesignStatus,
    toggleDesignFavorite,
  } = useDesignStore();
  const [keyword, setKeyword] = useState("");
  const [filter, setFilter] = useState<FilterOption>("最近创建");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const filtered = useMemo(() => {
    let list = savedDesigns.filter(
      (d) => d.name.includes(keyword) || d.style.includes(keyword),
    );
    switch (filter) {
      case "已收藏":
        list = list.filter((d) => d.isFavorite);
        break;
      case "客厅方案":
        list = list.filter((d) => d.rooms.includes("客厅"));
        break;
      case "全屋方案":
        list = list.filter((d) => d.rooms.includes("全屋"));
        break;
      case "高预算":
        list = [...list].sort((a, b) => b.budget - a.budget);
        break;
      case "低预算":
        list = [...list].sort((a, b) => a.budget - b.budget);
        break;
      default:
        break;
    }
    return list;
  }, [savedDesigns, keyword, filter]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <PageTitle
        title="我的方案"
        description="保存过的家装方案都在这里，随时查看、优化或导出。"
      />

      {savedDesigns.length === 0 ? (
        <div className="mt-8">
          <EmptyState
            icon={Home}
            title="还没有保存的家装方案"
            description="创建第一个方案，让 AI 帮你找到家的样子。"
            action={
              <Link to="/customize">
                <Button size="lg">开始创建</Button>
              </Link>
            }
          />
        </div>
      ) : (
        <>
          {/* 搜索 + 筛选 */}
          <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="relative sm:w-72">
              <Search className="absolute top-1/2 left-3.5 h-4 w-4 -translate-y-1/2 text-stone-300" />
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索方案名称或风格"
                className="w-full rounded-xl border border-cream-300 bg-white/80 py-2.5 pr-4 pl-10 text-sm text-stone-700 outline-none placeholder:text-stone-300 focus:border-sage-500 focus:ring-2 focus:ring-sage-100"
              />
            </div>
            <div className="thin-scrollbar flex gap-2 overflow-x-auto pb-1">
              {filterOptions.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setFilter(option)}
                  className={`shrink-0 rounded-full px-3.5 py-1.5 text-xs font-medium transition-all ${
                    filter === option
                      ? "bg-sage-600 text-white"
                      : "bg-cream-100 text-stone-500 hover:bg-cream-200"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="mt-8">
              <EmptyState
                title="没有匹配的方案"
                description="换个关键词或筛选条件试试。"
              />
            </div>
          ) : (
            <div className="mt-6 space-y-4">
              {filtered.map((design) => (
                <div
                  key={design.id}
                  className="flex flex-col gap-4 rounded-3xl border border-cream-200 bg-white/80 p-4 transition-all hover:shadow-card sm:flex-row sm:items-center"
                >
                  <div
                    className={`h-24 w-full shrink-0 rounded-2xl sm:w-36 ${design.coverGradient}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-display text-base font-semibold text-stone-800">
                        {design.name}
                      </h3>
                      <Tag tone={statusTone[design.status]}>{design.status}</Tag>
                      {design.isFavorite && (
                        <Heart className="h-4 w-4 fill-terra-500 text-terra-500" />
                      )}
                    </div>
                    <p className="mt-1.5 text-xs text-stone-400">
                      {design.createdAt} 创建 · {design.style} ·{" "}
                      {design.rooms.join(" / ")} ·{" "}
                      <span className="font-medium text-terra-600">
                        ¥{design.budget.toLocaleString()}
                      </span>
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate(`/design/${design.planId}`)}
                    >
                      <Eye className="h-4 w-4" />
                      查看
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        updateDesignStatus(design.id, "已优化");
                        navigate("/chat");
                      }}
                    >
                      <MessageCircleMore className="h-4 w-4" />
                      继续优化
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => updateDesignStatus(design.id, "已导出")}
                    >
                      <Download className="h-4 w-4" />
                      导出
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleDesignFavorite(design.id)}
                    >
                      <Heart
                        className={`h-4 w-4 ${design.isFavorite ? "fill-terra-500 text-terra-500" : ""}`}
                      />
                    </Button>
                    {pendingDelete === design.id ? (
                      <div className="flex items-center gap-1.5 rounded-xl bg-terra-50 px-2 py-1">
                        <span className="text-xs text-terra-600">确认删除？</span>
                        <Button
                          variant="terra"
                          size="sm"
                          onClick={() => {
                            removeDesign(design.id);
                            setPendingDelete(null);
                          }}
                        >
                          删除
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPendingDelete(null)}
                        >
                          取消
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setPendingDelete(design.id)}
                      >
                        <Trash2 className="h-4 w-4 text-stone-400" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
