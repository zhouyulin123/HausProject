import { ClipboardList, Brain, LayoutGrid, Save } from "lucide-react";
import SectionTitle from "@/components/common/SectionTitle";
import FadeIn from "@/components/common/FadeIn";

const steps = [
  {
    icon: ClipboardList,
    title: "输入户型与需求",
    description: "选择空间、填写面积预算，上传户型图更准确",
  },
  {
    icon: Brain,
    title: "AI 分析生活方式",
    description: "家庭成员、生活习惯都会成为方案的依据",
  },
  {
    icon: LayoutGrid,
    title: "生成多套方案",
    description: "布局、家具、色彩、预算，一次生成多套对比",
  },
  {
    icon: Save,
    title: "调整并保存设计",
    description: "和 AI 对话微调细节，满意后保存或导出",
  },
];

export default function ProcessSection() {
  return (
    <section className="bg-cream-100/60 py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <FadeIn>
          <SectionTitle
            eyebrow="工作流程"
            title="四步，看见你的理想家"
            description="不需要专业知识，跟着流程走，AI 会替你考虑设计的细节。"
          />
        </FadeIn>
        <div className="relative mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {/* 桌面端连接线 */}
          <div className="absolute top-7 right-[12%] left-[12%] hidden h-px border-t-2 border-dashed border-sage-200 lg:block" />
          {steps.map((step, i) => (
            <FadeIn key={step.title} delay={i * 0.08} className="relative">
              <div className="flex flex-col items-center text-center">
                <div className="relative z-10 flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-sage-600 shadow-card">
                  <step.icon className="h-6 w-6" strokeWidth={1.6} />
                  <span className="absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-terra-500 text-[10px] font-bold text-white">
                    {i + 1}
                  </span>
                </div>
                <h3 className="mt-4 text-base font-semibold text-stone-800">
                  {step.title}
                </h3>
                <p className="mt-1.5 max-w-[220px] text-sm leading-relaxed text-stone-500">
                  {step.description}
                </p>
              </div>
            </FadeIn>
          ))}
        </div>
      </div>
    </section>
  );
}
