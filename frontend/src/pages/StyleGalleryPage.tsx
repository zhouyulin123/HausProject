import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, X } from "lucide-react";
import type { StyleCase } from "@/types/design";
import { mockStyles, styleCategories } from "@/data/mockStyles";
import { useRequirementStore } from "@/store/useRequirementStore";
import StyleCard from "@/components/common/StyleCard";
import PageTitle from "@/components/common/PageTitle";
import Button from "@/components/common/Button";
import Tag from "@/components/common/Tag";

/** 风格名 → 定制表单中的风格选项映射 */
const styleNameMap: Record<string, string> = {
  日式侘寂: "日式风",
  法式复古: "法式风",
};

export default function StyleGalleryPage() {
  const navigate = useNavigate();
  const [category, setCategory] = useState("全部");
  const [detail, setDetail] = useState<StyleCase | null>(null);
  const { requirement, update } = useRequirementStore();

  const filtered = useMemo(
    () =>
      category === "全部"
        ? mockStyles
        : mockStyles.filter((s) => s.name === category),
    [category],
  );

  const applyStyle = (style: StyleCase) => {
    const mapped = styleNameMap[style.name] ?? style.name;
    if (!requirement.styles.includes(mapped)) {
      update({ styles: [...requirement.styles, mapped] });
    }
    navigate("/customize");
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageTitle
        title="发现你的理想家装风格"
        description="浏览不同风格的适用场景、配色与材质，一键套用到你的方案中。"
      />

      {/* 分类标签 */}
      <div className="thin-scrollbar mt-8 flex gap-2 overflow-x-auto pb-1">
        {styleCategories.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={`shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-all ${
              category === c
                ? "bg-sage-600 text-white shadow-card"
                : "border border-cream-300 bg-white/70 text-stone-600 hover:border-sage-400"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.map((style) => (
          <StyleCard
            key={style.id}
            style={style}
            onOpen={setDetail}
            onApply={applyStyle}
          />
        ))}
      </div>

      {/* 案例详情弹窗 */}
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
              className="thin-scrollbar max-h-[85vh] w-full max-w-xl overflow-y-auto rounded-3xl bg-cream-50 shadow-lift"
              onClick={(e) => e.stopPropagation()}
            >
              <div className={`relative h-40 ${detail.gradient}`}>
                <button
                  type="button"
                  onClick={() => setDetail(null)}
                  className="absolute top-3 right-3 flex h-8 w-8 items-center justify-center rounded-full bg-white/85 text-stone-500 hover:text-stone-800"
                >
                  <X className="h-4 w-4" />
                </button>
                <span className="absolute bottom-4 left-5 font-display text-xl font-semibold text-white drop-shadow-sm">
                  {detail.name}
                  <span className="ml-2 text-xs font-normal tracking-widest uppercase opacity-80">
                    {detail.english}
                  </span>
                </span>
              </div>
              <div className="space-y-5 p-6">
                <p className="text-sm leading-relaxed text-stone-600">
                  {detail.description}
                </p>
                <div>
                  <h4 className="text-sm font-semibold text-stone-700">适合人群</h4>
                  <p className="mt-1.5 text-sm text-stone-500">{detail.audience}</p>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-stone-700">常用配色</h4>
                  <div className="mt-2 flex gap-3">
                    {detail.palette.map((c) => (
                      <div key={c.name} className="text-center">
                        <span
                          className="block h-10 w-14 rounded-xl border border-stone-200/60 shadow-sm"
                          style={{ backgroundColor: c.hex }}
                        />
                        <span className="mt-1 block text-[11px] text-stone-400">
                          {c.name}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-stone-700">常用材质</h4>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {detail.materials.map((m) => (
                      <Tag key={m} tone="wood">
                        {m}
                      </Tag>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-stone-700">推荐家具</h4>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {detail.furniture.map((f) => (
                      <Tag key={f} tone="sage">
                        {f}
                      </Tag>
                    ))}
                  </div>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-stone-700">注意事项</h4>
                  <ul className="mt-1.5 list-inside list-disc space-y-1 text-sm text-stone-500">
                    {detail.cautions.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
                <Button className="w-full" onClick={() => applyStyle(detail)}>
                  <Sparkles className="h-4 w-4" />
                  套用此风格，开始定制
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
