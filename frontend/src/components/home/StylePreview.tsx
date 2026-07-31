import { Link, useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { mockStyles } from "@/data/mockStyles";
import SectionTitle from "@/components/common/SectionTitle";
import FadeIn from "@/components/common/FadeIn";
import Tag from "@/components/common/Tag";
import StyleImageCarousel from "@/components/common/StyleImageCarousel";

/** 首页风格案例区：紧凑卡片 */
export default function StylePreview() {
  const navigate = useNavigate();

  return (
    <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
      <FadeIn>
        <SectionTitle
          eyebrow="风格灵感"
          title="总有一种风格，是家的样子"
          description="选择你喜欢的风格，我们会帮你匹配色彩、家具和材质。"
        />
      </FadeIn>
      <div className="mt-10 grid grid-cols-2 gap-4 sm:gap-5 lg:grid-cols-4">
        {mockStyles.map((style, i) => (
          <FadeIn key={style.id} delay={Math.min(i * 0.05, 0.3)}>
            <div
              className="group block overflow-hidden rounded-3xl border border-cream-200 bg-white/70 transition-all duration-300 hover:-translate-y-1 hover:shadow-soft"
            >
              <StyleImageCarousel
                images={style.images}
                label={style.name}
                className="h-32 sm:h-36"
                intervalMs={5600 + i * 180}
                onOpen={() => navigate("/styles")}
                caption={
                  <span className="font-display text-xs tracking-widest text-white/90 uppercase drop-shadow-sm">
                    {style.english}
                  </span>
                }
              />
              <Link to="/styles" className="block p-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-stone-800 sm:text-base">
                    {style.name}
                  </h3>
                  <Tag tone="terra">{style.budgetTendency}</Tag>
                </div>
                <p className="mt-1.5 line-clamp-1 text-xs text-stone-400">
                  {style.audience}
                </p>
                <div className="mt-2.5 flex gap-1">
                  {style.palette.map((c) => (
                    <span
                      key={c.name}
                      className="h-3.5 w-3.5 rounded-full border border-white shadow-sm"
                      style={{ backgroundColor: c.hex }}
                      title={c.name}
                    />
                  ))}
                  <span className="ml-1 text-xs text-stone-400">
                    {style.colorKeywords.join(" · ")}
                  </span>
                </div>
              </Link>
            </div>
          </FadeIn>
        ))}
      </div>
      <FadeIn className="mt-8 text-center">
        <Link
          to="/styles"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-sage-700 hover:text-sage-600"
        >
          浏览全部风格案例
          <ArrowRight className="h-4 w-4" />
        </Link>
      </FadeIn>
    </section>
  );
}
