import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDownRight, ArrowUpRight, ScanLine, Sparkles } from "lucide-react";
import { fetchFurnitureCatalog } from "@/api/designApi";
import type { FurnitureItem } from "@/types/furniture";
import {
  SPACES,
  STYLES,
  heroSceneFor,
  type HeroSelectPayload,
  type SpaceName,
  type StyleName,
} from "@/lib/heroSceneData";

const HeroScene3D = lazy(() => import("./HeroScene3D"));

function HeroSceneFallback({ failed = false }: { failed?: boolean }) {
  return (
    <div className="flex h-full items-center justify-center bg-[#101611]">
      <div className="flex items-center gap-3 text-xs text-[#b8c5b8]">
        <span className="h-2 w-2 animate-pulse rounded-full bg-[#d5ff67]" />
        {failed ? "商品模型暂时不可用" : "正在构建数字空间"}
      </div>
    </div>
  );
}

const suggestionBySpace: Record<SpaceName, { budget: string; match: string }> = {
  客厅: { budget: "¥86,000", match: "98.2%" },
  卧室: { budget: "¥52,000", match: "97.6%" },
  餐厅: { budget: "¥38,000", match: "96.9%" },
};

export default function HeroSection() {
  const [space, setSpace] = useState<SpaceName>("客厅");
  const [style, setStyle] = useState<StyleName>("奶油风");
  const [selected, setSelected] = useState<HeroSelectPayload>(null);
  const [catalog, setCatalog] = useState<FurnitureItem[] | null>(null);
  const [catalogFailed, setCatalogFailed] = useState(false);
  const activeScene = useMemo(() => heroSceneFor(space, style), [space, style]);

  useEffect(() => {
    let active = true;
    void fetchFurnitureCatalog({ fallbackToMock: false })
      .then((products) => {
        if (!active) return;
        setCatalog(products);
        setCatalogFailed(false);
      })
      .catch(() => {
        if (!active) return;
        setCatalog([]);
        setCatalogFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);
  const sceneStats = useMemo(() => {
    const xs = activeScene.room.floorPolygon.map((point) => point.x);
    const zs = activeScene.room.floorPolygon.map((point) => point.z);
    const width = Math.max(...xs) - Math.min(...xs);
    const depth = Math.max(...zs) - Math.min(...zs);
    return [
      { value: `${width.toFixed(1)} × ${depth.toFixed(1)}m`, label: "空间尺寸" },
      { value: suggestionBySpace[space].budget, label: "建议预算" },
      { value: suggestionBySpace[space].match, label: "需求匹配" },
    ];
  }, [activeScene, space]);

  return (
    <section className="home-hero home-grid relative overflow-hidden bg-[#0b0f0c] text-[#f1efe7]">
      <div className="absolute inset-0" aria-label={`${style}${space}交互式三维空间预览`}>
        <Suspense fallback={<HeroSceneFallback />}>
          {catalog?.length ? (
            <HeroScene3D scene={activeScene} catalog={catalog} onSelectItem={setSelected} />
          ) : (
            <HeroSceneFallback failed={catalogFailed} />
          )}
        </Suspense>
      </div>

      <div className="home-noise pointer-events-none absolute inset-0 opacity-25" />
      <div className="home-hero-tone pointer-events-none absolute inset-0" />
      <div className="home-scan-line pointer-events-none absolute inset-x-0 top-0 z-[2] h-px bg-[#d5ff67]/65 shadow-[0_0_22px_#d5ff67]" />

      <div className="pointer-events-none relative z-10 mx-auto min-h-[inherit] max-w-[1500px]">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65 }}
          className="absolute top-6 right-5 left-5 flex items-center justify-between gap-4 sm:right-8 sm:left-8 lg:top-9 lg:right-12 lg:left-12"
        >
          <span className="flex items-center gap-3 text-[10px] text-[#b7c1b7]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#d5ff67] shadow-[0_0_14px_#d5ff67]" />
            HAUS / 空间智能系统
          </span>
          <span className="hidden items-center gap-2 text-[10px] text-[#d5ff67] sm:flex">
            <ScanLine className="h-3.5 w-3.5" />
            实时空间推演
          </span>
        </motion.div>

        <div className="flex min-h-[inherit] w-full flex-col justify-center px-5 pt-24 pb-44 sm:px-8 sm:pb-48 lg:w-[49%] lg:px-12 lg:pt-28 lg:pb-28 xl:px-16">
          <motion.div
            initial={{ opacity: 0, y: 26 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.85, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="mb-5 flex items-center gap-3 text-xs text-[#d5ff67] sm:mb-7">
              <Sparkles className="h-4 w-4" />
              <span>从一张照片开始设计</span>
            </div>
            <h1 className="max-w-[620px] font-display text-[clamp(3.25rem,6vw,5.9rem)] leading-[0.94] font-medium tracking-normal text-[#f4f1e8]">
              AI 家装，<br />
              <span className="text-[#b6c2b2] italic">预见家的</span><br />
              下一种可能。
            </h1>
            <p className="mt-6 max-w-md text-sm leading-7 text-[#b2bbb2] sm:mt-8 sm:text-base">
              上传真实空间，告诉 AI 你的生活方式。我们把户型、采光、动线与预算放进同一次推演，生成可以继续编辑、也能真正落地的方案。
            </p>
            <div className="pointer-events-auto mt-7 flex flex-wrap items-center gap-3 sm:mt-9">
              <Link
                to="/design/new"
                className="group inline-flex items-center gap-7 rounded-full bg-[#d5ff67] px-6 py-3.5 text-sm font-semibold text-[#11150f] transition-colors hover:bg-[#e0ff91]"
              >
                开始设计我的家
                <ArrowUpRight className="h-4 w-4 transition-transform group-hover:rotate-45" />
              </Link>
              <Link
                to="/styles"
                className="inline-flex items-center gap-2 px-3 py-3 text-sm text-[#d2d8d1] transition-colors hover:text-white"
              >
                先看真实案例
                <ArrowDownRight className="h-4 w-4" />
              </Link>
            </div>
          </motion.div>

          <div className="mt-10 hidden grid-cols-3 border-t border-white/12 pt-5 sm:grid lg:mt-12">
            {sceneStats.map((stat, index) => (
              <div key={stat.label} className={index > 0 ? "border-l border-white/12 px-4" : "pr-4"}>
                <p className="font-mono text-sm text-[#f0f1e9] sm:text-base">{stat.value}</p>
                <p className="mt-1 text-[9px] text-[#7f8a80]">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="pointer-events-auto absolute top-16 right-5 sm:top-20 sm:right-8 lg:top-24 lg:right-12">
          <div className="flex gap-1 rounded-full border border-white/12 bg-[#0b0f0c]/70 p-1 backdrop-blur-xl" aria-label="选择空间类型">
            {SPACES.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={space === option}
                onClick={() => {
                  setSpace(option);
                  setSelected(null);
                }}
                className={`rounded-full px-3 py-1.5 text-[11px] transition-colors ${
                  space === option ? "bg-[#f0eee6] text-[#11150f]" : "text-[#bdc5bd] hover:text-white"
                }`}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="pointer-events-auto absolute right-5 bottom-5 left-5 sm:right-8 sm:bottom-8 sm:left-auto sm:w-[min(48rem,58%)] lg:right-12 lg:bottom-10">
          <AnimatePresence mode="wait">
            <motion.div
              key={selected?.name ?? space}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="mb-4 hidden max-w-md border-l border-[#d5ff67] bg-[#0b0f0c]/72 px-4 py-3 backdrop-blur-xl sm:block"
            >
              <p className="text-[10px] text-[#d5ff67]">{selected ? `AI 设计依据 / ${selected.name}` : "AI 空间观察"}</p>
              <p className="mt-1.5 text-xs leading-5 text-[#cbd2ca]">
                {selected?.tip ?? "点击任意家具，查看尺寸与摆放依据。"}
              </p>
            </motion.div>
          </AnimatePresence>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[9px] text-[#8e988f]">当前方案</p>
              <p className="mt-1 font-display text-xl tracking-normal text-white sm:text-2xl">{style} · {space}</p>
            </div>
            <div className="flex max-w-full gap-1 overflow-x-auto rounded-full border border-white/12 bg-[#0b0f0c]/72 p-1 backdrop-blur-xl" aria-label="选择设计风格">
              {STYLES.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={style === option}
                  onClick={() => setStyle(option)}
                  className={`shrink-0 rounded-full px-3 py-1.5 text-[10px] transition-colors ${
                    style === option ? "bg-[#d5ff67] text-[#11150f]" : "text-[#aab4aa] hover:text-white"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
