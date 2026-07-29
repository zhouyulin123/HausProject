import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

const defaultLines = [
  "AI 正在分析你的空间动线、采光条件和收纳需求...",
  "正在匹配适合你生活方式的风格与材质...",
  "正在为你计算预算分配与家具清单...",
];

/** AI 分析中的 loading 状态：打字点 + 轮播文案 */
export default function LoadingAI({
  lines = defaultLines,
  compact = false,
}: {
  lines?: string[];
  compact?: boolean;
}) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(
      () => setIndex((i) => (i + 1) % lines.length),
      1800,
    );
    return () => clearInterval(timer);
  }, [lines.length]);

  if (compact) {
    return (
      <div className="flex items-center gap-2 text-sm text-stone-500">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-5 py-20 text-center">
      <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-sage-600 text-white shadow-soft">
        <Sparkles className="h-7 w-7 animate-pulse" />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </div>
      <p className="max-w-md text-sm text-stone-500 transition-all">{lines[index]}</p>
    </div>
  );
}
