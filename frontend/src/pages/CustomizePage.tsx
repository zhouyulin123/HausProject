import StepForm from "@/components/customize/StepForm";
import RequirementSummary from "@/components/customize/RequirementSummary";
import PageTitle from "@/components/common/PageTitle";

export default function CustomizePage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <PageTitle
        title="告诉 AI 你想要的家"
        description="从户型、预算到生活习惯，AI 会综合生成更适合你的家装建议。全程约 2 分钟。"
      />

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[1fr_320px]">
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
    </div>
  );
}
