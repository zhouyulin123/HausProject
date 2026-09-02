import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Box, ChevronLeft, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { fetchFurnitureCatalog } from "@/api/designApi";
import type { FurnitureItem } from "@/types/furniture";
import {
  featuredFurniture,
  furnitureMediaModes,
  type FurnitureMediaMode,
} from "@/lib/furnitureMedia";

const FurnitureModelViewer = lazy(
  () => import("@/components/furniture/FurnitureModelViewer"),
);

function MediaFallback() {
  return (
    <div className="flex h-full items-center justify-center bg-[#e5e1d6]">
      <span className="h-2 w-2 animate-pulse rounded-full bg-[#526349]" />
    </div>
  );
}

export default function FurnitureModelShowcase() {
  const [items, setItems] = useState<FurnitureItem[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [mediaMode, setMediaMode] = useState<FurnitureMediaMode>("3d");

  useEffect(() => {
    let cancelled = false;
    void fetchFurnitureCatalog({ fallbackToMock: false })
      .then((catalog) => {
        if (!cancelled) setItems(featuredFurniture(catalog));
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      });
    return () => { cancelled = true; };
  }, []);

  const active = items[activeIndex];
  const modes = useMemo(() => active ? furnitureMediaModes(active) : [], [active]);

  useEffect(() => {
    if (!active) return;
    setMediaMode(modes[0] ?? "3d");
    const timer = window.setInterval(() => {
      if (modes.length > 1) {
        setMediaMode((current) => current === "image" ? "3d" : "image");
      } else {
        setActiveIndex((current) => (current + 1) % items.length);
      }
    }, 7000);
    return () => window.clearInterval(timer);
  }, [active, items.length, modes]);

  const selectOffset = (offset: number) => {
    setActiveIndex((current) => (current + offset + items.length) % items.length);
  };

  if (!active) return null;

  return (
    <section className="border-y border-[#1d241f]/15 bg-[#dcd9cf] px-5 py-20 sm:px-8 lg:px-12 lg:py-28">
      <div className="mx-auto grid max-w-[1400px] gap-10 lg:grid-cols-[0.72fr_1.28fr] lg:items-stretch">
        <div className="flex flex-col justify-between py-2">
          <div>
            <p className="font-mono text-[10px] tracking-[0.22em] text-[#667067] uppercase">
              01 / Living model index
            </p>
            <h2 className="mt-6 font-display text-4xl leading-[1.02] sm:text-6xl">
              家具不等图片，<br />先以明确尺寸存在。
            </h2>
            <p className="mt-7 max-w-md text-sm leading-7 text-[#626c64]">
              目录尺寸、材质与结构共同构成可进入空间方案的数字家具资产。
            </p>
          </div>
          <div className="mt-12 flex items-end justify-between gap-6 border-t border-[#1d241f]/15 pt-6">
            <div>
              <p className="font-mono text-[10px] tracking-[0.16em] text-[#727c73] uppercase">
                Model / {active.sku ?? active.id}
              </p>
              <h3 className="mt-2 font-display text-2xl">{active.name}</h3>
              <p className="mt-1 text-xs text-[#6c756d]">{active.sizeSuggestion} · {active.material}</p>
            </div>
            <Link to="/furniture" className="border-b border-[#1d241f]/35 pb-1 text-xs text-[#313a33]">
              查看目录
            </Link>
          </div>
        </div>

        <div className="relative min-h-[430px] overflow-hidden bg-[#eee9de] sm:min-h-[560px]">
          <div className="absolute inset-0">
            {active.modelSpecJson ? (
              <Suspense fallback={<MediaFallback />}>
                <FurnitureModelViewer spec={active.modelSpecJson} enableZoom={false} />
              </Suspense>
            ) : (
              <MediaFallback />
            )}
          </div>
          <AnimatePresence>
            {mediaMode === "image" && active.imageUrl && (
              <motion.img
                key={active.imageUrl}
                src={active.imageUrl}
                alt={active.name}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.35 }}
                className="absolute inset-0 h-full w-full object-cover"
              />
            )}
          </AnimatePresence>

          <div className="pointer-events-none absolute top-5 left-5 flex items-center gap-2 rounded-full border border-[#1d241f]/10 bg-white/70 px-3 py-2 font-mono text-[9px] tracking-[0.16em] text-[#435044] uppercase backdrop-blur">
            <Box className="h-3.5 w-3.5" /> {mediaMode === "3d" ? "Live 3D" : "Product Image"}
          </div>
          <div className="absolute right-5 bottom-5 flex items-center gap-2">
            <button type="button" onClick={() => selectOffset(-1)} title="上一个模型" className="flex h-10 w-10 items-center justify-center rounded-full border border-[#1d241f]/15 bg-white/80 text-[#273028] backdrop-blur hover:bg-white">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-14 text-center font-mono text-[10px] text-[#626c64]">
              {String(activeIndex + 1).padStart(2, "0")} / {String(items.length).padStart(2, "0")}
            </span>
            <button type="button" onClick={() => selectOffset(1)} title="下一个模型" className="flex h-10 w-10 items-center justify-center rounded-full border border-[#1d241f]/15 bg-white/80 text-[#273028] backdrop-blur hover:bg-white">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          {modes.length > 1 && (
            <div className="absolute top-5 right-5 flex rounded-full border border-[#1d241f]/10 bg-white/75 p-1 backdrop-blur">
              {modes.map((mode) => (
                <button key={mode} type="button" onClick={() => setMediaMode(mode)} className={`rounded-full px-3 py-1.5 font-mono text-[9px] uppercase ${mediaMode === mode ? "bg-[#273128] text-white" : "text-[#606961]"}`}>
                  {mode}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
