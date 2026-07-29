import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Heart, Plus, X } from "lucide-react";
import type { FurnitureItem } from "@/types/furniture";
import { furnitureMaterials, furniturePriceRanges } from "@/data/mockFurniture";
import { fetchFurnitureCatalog } from "@/api/designApi";
import FurnitureCard from "@/components/furniture/FurnitureCard";
import FurnitureFilter, {
  defaultFilters,
} from "@/components/furniture/FurnitureFilter";
import type { FurnitureFilters } from "@/components/furniture/FurnitureFilter";
import PageTitle from "@/components/common/PageTitle";
import EmptyState from "@/components/common/EmptyState";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";
import { useDesignStore } from "@/store/useDesignStore";

/** 从价格区间文本中提取最低价，用于价格筛选 */
function minPrice(priceRange: string): number {
  const match = priceRange.replace(/,/g, "").match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function matchPrice(item: FurnitureItem, band: string): boolean {
  const price = minPrice(item.priceRange);
  switch (band) {
    case "1000 以下":
      return price < 1000;
    case "1000 - 3000":
      return price >= 1000 && price < 3000;
    case "3000 - 5000":
      return price >= 3000 && price < 5000;
    case "5000 以上":
      return price >= 5000;
    default:
      return true;
  }
}

export default function FurniturePage() {
  const [filters, setFilters] = useState<FurnitureFilters>(defaultFilters);
  const [detail, setDetail] = useState<FurnitureItem | null>(null);
  const [catalog, setCatalog] = useState<FurnitureItem[]>([]);
  const [loading, setLoading] = useState(true);
  const {
    favoriteFurnitureIds,
    toggleFurnitureFavorite,
    pickedFurnitureIds,
    togglePickedFurniture,
  } = useDesignStore();

  useEffect(() => {
    let cancelled = false;
    void fetchFurnitureCatalog().then((items) => {
      if (cancelled) return;
      setCatalog(items);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // 筛选可选项跟随商品库动态生成
  const optionGroups = useMemo(() => {
    const distinct = (get: (i: FurnitureItem) => string) => [
      "全部",
      ...Array.from(new Set(catalog.map(get).filter(Boolean))),
    ];
    return {
      rooms: distinct((i) => i.room),
      categories: distinct((i) => i.category),
      styles: distinct((i) => i.style),
      prices: furniturePriceRanges,
      materials: furnitureMaterials,
    };
  }, [catalog]);

  const filtered = useMemo(
    () =>
      catalog.filter(
        (item) =>
          (filters.room === "全部" || item.room === filters.room) &&
          (filters.category === "全部" || item.category === filters.category) &&
          (filters.style === "全部" || item.style === filters.style) &&
          (filters.material === "全部" || item.material.includes(filters.material)) &&
          matchPrice(item, filters.price),
      ),
    [catalog, filters],
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageTitle
        title="AI 家具推荐"
        description="每一件推荐都基于你的空间尺寸、风格偏好与生活习惯，附上推荐理由。"
        extra={
          pickedFurnitureIds.length > 0 ? (
            <Tag tone="sage">已加入方案 {pickedFurnitureIds.length} 件</Tag>
          ) : undefined
        }
      />

      <div className="mt-8 space-y-6">
        <FurnitureFilter
          filters={filters}
          onChange={(patch) => setFilters((f) => ({ ...f, ...patch }))}
          optionGroups={optionGroups}
        />

        {loading ? (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-80 animate-pulse rounded-3xl border border-cream-200 bg-cream-100/70"
              />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title="没有符合条件的家具"
            description="换个筛选条件试试，或让 AI 在对话中为你专门推荐。"
            action={
              <Button variant="outline" onClick={() => setFilters(defaultFilters)}>
                清空筛选
              </Button>
            }
          />
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filtered.map((item) => (
              <FurnitureCard key={item.id} item={item} onOpen={setDetail} />
            ))}
          </div>
        )}
      </div>

      {/* 商品详情弹窗 */}
      <AnimatePresence>
        {detail && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4 backdrop-blur-sm"
            onClick={() => setDetail(null)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.94, y: 16 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.94, y: 16 }}
              transition={{ duration: 0.25 }}
              className="w-full max-w-lg overflow-hidden rounded-3xl bg-cream-50 shadow-lift"
              onClick={(e) => e.stopPropagation()}
            >
              <div className={`relative h-48 overflow-hidden ${detail.gradient}`}>
                {detail.imageUrl && (
                  <img
                    src={detail.imageUrl}
                    alt={detail.name}
                    className="absolute inset-0 h-full w-full object-cover"
                  />
                )}
                <button
                  type="button"
                  onClick={() => setDetail(null)}
                  className="absolute top-3 right-3 flex h-8 w-8 items-center justify-center rounded-full bg-white/85 text-stone-500 hover:text-stone-800"
                >
                  <X className="h-4 w-4" />
                </button>
                <span className="absolute bottom-3 left-4 rounded-full bg-white/85 px-2.5 py-1 text-xs font-semibold text-sage-700">
                  匹配 {detail.matchScore}%
                </span>
              </div>
              <div className="p-6">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-lg font-semibold text-stone-800">{detail.name}</h3>
                  <span className="shrink-0 font-display text-base font-semibold text-terra-600">
                    {detail.priceRange}
                  </span>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <Tag tone="wood">{detail.style}</Tag>
                  <Tag tone="cream">{detail.room}</Tag>
                  <Tag tone="cream">{detail.category}</Tag>
                  <Tag tone="cream">{detail.material}</Tag>
                </div>
                <div className="mt-4 space-y-3 text-sm leading-relaxed text-stone-600">
                  <p>
                    <span className="font-semibold text-stone-700">推荐理由：</span>
                    {detail.reason}
                  </p>
                  <p>
                    <span className="font-semibold text-stone-700">尺寸建议：</span>
                    {detail.sizeSuggestion}
                  </p>
                  <p>
                    <span className="font-semibold text-stone-700">替代选择：</span>
                    {detail.alternative}
                  </p>
                </div>
                <div className="mt-6 flex gap-2">
                  <Button
                    className="flex-1"
                    variant={pickedFurnitureIds.includes(detail.id) ? "secondary" : "primary"}
                    onClick={() => togglePickedFurniture(detail.id)}
                  >
                    {pickedFurnitureIds.includes(detail.id) ? (
                      <>
                        <Check className="h-4 w-4 text-sage-600" />
                        已加入方案
                      </>
                    ) : (
                      <>
                        <Plus className="h-4 w-4" />
                        加入当前方案
                      </>
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => toggleFurnitureFavorite(detail.id)}
                  >
                    <Heart
                      className={`h-4 w-4 ${
                        favoriteFurnitureIds.includes(detail.id)
                          ? "fill-terra-500 text-terra-500"
                          : ""
                      }`}
                    />
                    {favoriteFurnitureIds.includes(detail.id) ? "已收藏" : "收藏"}
                  </Button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
