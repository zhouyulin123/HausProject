import { Link } from "react-router-dom";
import { Brain, LayoutGrid, Armchair, Calculator, ArrowRight } from "lucide-react";
import HeroSection from "@/components/home/HeroSection";
import FeatureCard from "@/components/home/FeatureCard";
import StylePreview from "@/components/home/StylePreview";
import ProcessSection from "@/components/home/ProcessSection";
import SectionTitle from "@/components/common/SectionTitle";
import FadeIn from "@/components/common/FadeIn";
import Button from "@/components/common/Button";

const features = [
  {
    icon: Brain,
    title: "AI 智能需求理解",
    description: "用一句话描述想要的家，AI 自动整理出结构化的装修需求清单。",
  },
  {
    icon: LayoutGrid,
    title: "多风格家装方案生成",
    description: "一次生成多套风格方案，布局、色彩、材质一步到位，直观对比。",
  },
  {
    icon: Armchair,
    title: "家具与软装智能推荐",
    description: "根据空间尺寸与生活习惯推荐家具清单，每一件都有推荐理由。",
  },
  {
    icon: Calculator,
    title: "预算与采购清单估算",
    description: "硬装、定制、家具、软装分项估算，预算花在哪里一目了然。",
  },
];

export default function HomePage() {
  return (
    <div>
      <HeroSection />

      {/* 功能亮点 */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <FadeIn>
          <SectionTitle
            eyebrow="核心能力"
            title="AI 贯穿家装决策的每一步"
            description="你的家不只是好看，还要适合每天的生活。"
          />
        </FadeIn>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((f, i) => (
            <FadeIn key={f.title} delay={i * 0.06}>
              <FeatureCard {...f} />
            </FadeIn>
          ))}
        </div>
      </section>

      <StylePreview />
      <ProcessSection />

      {/* 底部 CTA */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6">
        <FadeIn>
          <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-sage-600 to-sage-700 px-6 py-14 text-center shadow-lift sm:px-12">
            <div className="pointer-events-none absolute -top-16 -right-16 h-56 w-56 rounded-full bg-white/10 blur-2xl" />
            <div className="pointer-events-none absolute -bottom-20 -left-10 h-56 w-56 rounded-full bg-terra-300/20 blur-2xl" />
            <h2 className="relative font-display text-2xl font-semibold text-white sm:text-3xl">
              你的理想家，可以先从一个 AI 方案开始。
            </h2>
            <p className="relative mt-3 text-sm text-sage-100 sm:text-base">
              免费生成，三分钟看到布局、家具与预算建议。
            </p>
            <Link to="/customize" className="relative mt-8 inline-block">
              <Button variant="terra" size="lg">
                创建我的家装方案
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </FadeIn>
      </section>
    </div>
  );
}
