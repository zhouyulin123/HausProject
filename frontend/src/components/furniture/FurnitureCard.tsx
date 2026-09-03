import { Box, Check, Heart, Plus } from "lucide-react";
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
    <div className="group flex flex-col overflow-hidden rounded-[1.5rem] border border-[#1d241f]/15 bg-[#e7e4da] transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_24px_55px_rgb(20_28_22/.14)]">
      <button
        type="button"
        onClick={() => onOpen(item)}
        className={`relative h-48 cursor-pointer overflow-hidden ${item.gradient}`}
      >
        {item.imageUrl && (
          <img
            src={item.imageUrl}
            alt={item.name}
            className="absolute inset-0 h-full w-full object-cover"
          />
        )}
        {!item.imageUrl && item.modelSpecJson && (
          <div className="absolute inset-0 overflow-hidden bg-[#202820] text-[#dfe8d7]">
            <div className="home-plan-grid absolute inset-0 opacity-45" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_66%_34%,rgba(213,255,103,.16),transparent_42%)]" />
            <div className="absolute top-1/2 left-1/2 flex h-24 w-24 -translate-x-1/2 -translate-y-1/2 items-center justify-center border border-[#d5ff67]/30 [transform:translate(-50%,-50%)_rotate(45deg)]">
              <Box className="h-10 w-10 -rotate-45 text-[#d5ff67]" strokeWidth={1.2} />
            </div>
            <span className="absolute right-3 bottom-3 rounded-full border border-white/15 bg-black/20 px-2.5 py-1 font-mono text-[9px] tracking-[0.14em] uppercase backdrop-blur">
              3D Model
            </span>
          </div>
        )}
        {item.matchScore !== undefined && (
          <span className="absolute top-3 left-3 rounded-full bg-white/85 px-2.5 py-1 text-xs font-semibold text-sage-700 backdrop-blur">
            匹配 {item.matchScore}%
          </span>
        )}
        <span className="absolute bottom-3 left-3 font-mono text-[9px] tracking-[0.14em] text-white/80 uppercase">Object / {item.sku ?? item.id}</span>
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
