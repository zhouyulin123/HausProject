import { Link } from "react-router-dom";
import { ArrowRight, Lightbulb } from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import RequirementSummary from "@/components/customize/RequirementSummary";
import { mockStyles } from "@/data/mockStyles";

const inspirations = mockStyles.slice(0, 3);

export default function ChatPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="grid items-start gap-6 xl:grid-cols-[300px_1fr_280px]">
        {/* 左侧：需求摘要（桌面端） */}
        <div className="sticky top-24 hidden xl:block">
          <RequirementSummary />
        </div>

        {/* 中间：对话区 */}
        <div>
          <div className="mb-4">
            <h1 className="text-xl font-semibold sm:text-2xl">和 AI 设计师聊聊</h1>
            <p className="mt-1.5 text-sm text-stone-500">
              像和设计师沟通一样补充需求，AI 会记住每一个细节。
            </p>
          </div>
          <ChatPanel />
        </div>

        {/* 右侧：灵感卡片（大屏） */}
        <div className="sticky top-24 hidden space-y-4 xl:block">
          <div className="rounded-3xl border border-cream-200 bg-white/80 p-5">
            <div className="flex items-center gap-2 text-sm font-semibold text-stone-700">
              <Lightbulb className="h-4 w-4 text-terra-500" />
              灵感参考
            </div>
            <div className="mt-4 space-y-3">
              {inspirations.map((style) => (
                <Link
                  key={style.id}
                  to="/styles"
                  className="group block overflow-hidden rounded-2xl border border-cream-200 transition-all hover:shadow-card"
                >
                  <div className={`h-16 ${style.gradient}`} />
                  <div className="flex items-center justify-between px-3 py-2.5">
                    <span className="text-xs font-semibold text-stone-700">
                      {style.name}
                    </span>
                    <ArrowRight className="h-3.5 w-3.5 text-stone-300 transition-transform group-hover:translate-x-0.5 group-hover:text-sage-600" />
                  </div>
                </Link>
              ))}
            </div>
          </div>
          <div className="rounded-3xl bg-sage-600 p-5 text-white">
            <p className="text-sm leading-relaxed">
              “正在分析你的空间动线、采光条件和收纳需求，聊得越多，方案越贴合你的生活。”
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
