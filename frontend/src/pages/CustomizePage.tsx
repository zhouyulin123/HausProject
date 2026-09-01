import StepForm from "@/components/customize/StepForm";
import RequirementSummary from "@/components/customize/RequirementSummary";
import StudioPage from "@/components/layout/StudioPage";

export default function CustomizePage() {
  return (
    <StudioPage
      title="先定义生活，再设计空间。"
      description="告诉 AI 你的户型、预算和日常习惯。每一个选择都会成为空间推演中的真实约束，而不是一份被遗忘的问卷。"
    >
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_320px]">
        <StepForm />

        {/* 桌面端：右侧固定摘要 */}
        <div className="sticky top-24 hidden lg:block">
          <RequirementSummary />
        </div>

        {/* 移动端：底部可折叠摘要 */}
        <details className="rounded-3xl border border-cream-200 bg-white/70 lg:hidden">
          <summary className="cursor-pointer px-5 py-4 text-sm font-semibold text-stone-700">
            查看需求摘要
          </summary>
          <div className="px-2 pb-2">
            <RequirementSummary compact />
          </div>
        </details>
      </div>
    </StudioPage>
  );
}
