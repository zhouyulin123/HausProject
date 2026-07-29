import { Check, Heart, Plus } from "lucide-react";
import type { FurnitureItem } from "@/types/furniture";
import { useDesignStore } from "@/store/useDesignStore";
import Tag from "@/components/common/Tag";
import Button from "@/components/common/Button";

export default function FurnitureCard({
  item,
  onOpen,
}: {
  item: FurnitureItem;
  onOpen: (item: FurnitureItem) => void;
}) {
  const {
    favoriteFurnitureIds,
    toggleFurnitureFavorite,
    pickedFurnitureIds,
    togglePickedFurniture,
  } = useDesignStore();
  const favorite = favoriteFurnitureIds.includes(item.id);
  const picked = pickedFurnitureIds.includes(item.id);

  return (
    <div className="group flex flex-col overflow-hidden rounded-3xl border border-cream-200 bg-white/80 transition-all duration-300 hover:-translate-y-1 hover:shadow-soft">
      <button
        type="button"
        onClick={() => onOpen(item)}
        className={`relative h-40 cursor-pointer overflow-hidden ${item.gradient}`}
      >
        {item.imageUrl && (
          <img
            src={item.imageUrl}
            alt={item.name}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        <span className="absolute top-3 left-3 rounded-full bg-white/85 px-2.5 py-1 text-xs font-semibold text-sage-700 backdrop-blur">
          匹配 {item.matchScore}%
        </span>
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            toggleFurnitureFavorite(item.id);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.stopPropagation();
              toggleFurnitureFavorite(item.id);
            }
          }}
          className={`absolute top-3 right-3 flex h-8 w-8 items-center justify-center rounded-full backdrop-blur transition-all ${
            favorite
              ? "bg-terra-500 text-white"
              : "bg-white/85 text-stone-400 hover:text-terra-500"
          }`}
          title={favorite ? "取消收藏" : "收藏"}
        >
          <Heart className={`h-4 w-4 ${favorite ? "fill-current" : ""}`} />
        </span>
      </button>
      <div className="flex flex-1 flex-col p-4">
        <div className="flex items-start justify-between gap-2">
          <button
            type="button"
            onClick={() => onOpen(item)}
            className="text-left text-sm font-semibold text-stone-800 hover:text-sage-700"
          >
            {item.name}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Tag tone="wood">{item.style}</Tag>
          <Tag tone="cream">{item.room}</Tag>
          <Tag tone="cream">{item.material}</Tag>
        </div>
        <p className="mt-2.5 line-clamp-2 text-xs leading-relaxed text-stone-500">
          {item.reason}
        </p>
        <div className="mt-auto flex items-center justify-between pt-4">
          <span className="text-sm font-semibold text-terra-600">{item.priceRange}</span>
          <Button
            size="sm"
            variant={picked ? "secondary" : "primary"}
            onClick={() => togglePickedFurniture(item.id)}
          >
            {picked ? <Check className="h-3.5 w-3.5 text-sage-600" /> : <Plus className="h-3.5 w-3.5" />}
            {picked ? "已加入" : "加入方案"}
          </Button>
        </div>
      </div>
    </div>
  );
}
