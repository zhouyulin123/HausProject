import { Heart, ArrowUpRight } from "lucide-react";
import { useState } from "react";
import type { StyleCase } from "@/types/design";
import Tag from "./Tag";
import Button from "./Button";

export default function StyleCard({
  style,
  onOpen,
  onApply,
}: {
  style: StyleCase;
  onOpen: (style: StyleCase) => void;
  onApply: (style: StyleCase) => void;
}) {
  const [favorite, setFavorite] = useState(false);

  return (
    <div className="group flex flex-col overflow-hidden rounded-3xl border border-cream-200 bg-white/80 transition-all duration-300 hover:-translate-y-1 hover:shadow-soft">
      <button
        type="button"
        onClick={() => onOpen(style)}
        className={`relative h-40 cursor-pointer ${style.gradient}`}
      >
        <span className="absolute bottom-3 left-4 font-display text-xs tracking-widest text-white/85 uppercase">
          {style.english}
        </span>
        <span
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            setFavorite((v) => !v);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.stopPropagation();
              setFavorite((v) => !v);
            }
          }}
          className={`absolute top-3 right-3 flex h-8 w-8 items-center justify-center rounded-full backdrop-blur transition-all ${
            favorite
              ? "bg-terra-500 text-white"
              : "bg-white/85 text-stone-400 hover:text-terra-500"
          }`}
        >
          <Heart className={`h-4 w-4 ${favorite ? "fill-current" : ""}`} />
        </span>
      </button>
      <div className="flex flex-1 flex-col p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-stone-800">{style.name}</h3>
          <Tag tone="terra">{style.budgetTendency}</Tag>
        </div>
        <p className="mt-1.5 text-xs text-stone-400">适合：{style.audience}</p>
        <div className="mt-2.5 flex items-center gap-1.5">
          {style.palette.map((c) => (
            <span
              key={c.name}
              className="h-4 w-4 rounded-full border border-white shadow-sm"
              style={{ backgroundColor: c.hex }}
              title={c.name}
            />
          ))}
          <span className="ml-1 text-xs text-stone-400">
            {style.colorKeywords.join(" · ")}
          </span>
        </div>
        <p className="mt-2 text-xs text-stone-400">户型：{style.suitableLayout}</p>
        <div className="mt-auto flex gap-2 pt-4">
          <Button size="sm" className="flex-1" onClick={() => onApply(style)}>
            套用此风格
          </Button>
          <Button size="sm" variant="outline" onClick={() => onOpen(style)}>
            详情
            <ArrowUpRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
