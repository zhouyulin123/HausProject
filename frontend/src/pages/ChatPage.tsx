import { Link } from "react-router-dom";
import { ArrowRight, Lightbulb } from "lucide-react";
import ChatPanel from "@/components/chat/ChatPanel";
import RequirementSummary from "@/components/customize/RequirementSummary";
import { mockStyles } from "@/data/mockStyles";
import StudioPage from "@/components/layout/StudioPage";

const inspirations = mockStyles.slice(0, 3);

export default function ChatPage() {
  return (
    <StudioPage
      title="把模糊的喜欢，说清楚。"
      description="像面对真正的设计师一样交流。AI 会追问影响空间决策的细节，并把每次回答同步回你的设计简报。"
    >
      <div className="grid items-start gap-6 xl:grid-cols-[300px_1fr_280px]">
        {/* 左侧：需求摘要（桌面端） */}
        <div className="sticky top-24 hidden xl:block">
          <RequirementSummary />
        </div>

        {/* 中间：对话区 */}
        <div>
          <div className="mb-4 flex items-center justify-between border-b border-[#1d241f]/15 pb-3">
            <div className="flex items-center gap-2 text-[10px] tracking-[0.18em] text-[#59645b] uppercase">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#5f7350]" />
              AI Designer / Online
            </div>
            <span className="font-mono text-[10px] text-[#7c867e]">SESSION 03</span>
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
    </StudioPage>
  );
}
