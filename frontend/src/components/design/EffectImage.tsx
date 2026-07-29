import { useState } from "react";
import { motion } from "framer-motion";
import { ImageIcon, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { renderEffectImage } from "@/api/designApi";
import type { DesignPlan } from "@/types/design";

type Status = "idle" | "loading" | "done" | "error";

const loadingLines = [
  "AI 正在绘制效果图...",
  "正在锁定户型结构、铺陈家具...",
  "正在渲染灯光与材质质感...",
];

/** 方案主效果图：按需调用本地 SD 生成，未生成时展示占位 + 按钮 */
export default function EffectImage({ plan }: { plan: DesignPlan }) {
  const [status, setStatus] = useState<Status>("idle");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [mode, setMode] = useState<string>("");
  const [lineIndex, setLineIndex] = useState(0);

  const run = async () => {
    setStatus("loading");
    setLineIndex(0);
    const timer = setInterval(
      () => setLineIndex((i) => (i + 1) % loadingLines.length),
      2500,
    );
    try {
      const result = await renderEffectImage(plan.id, plan.style);
      setImageUrl(result.imageUrl);
      setMode(result.mode);
      setStatus("done");
    } catch {
      setStatus("error");
    } finally {
      clearInterval(timer);
    }
  };

  return (
    <div className={`relative h-64 overflow-hidden rounded-3xl ${plan.coverGradient}`}>
      {/* 注意：这里不能用 AnimatePresence——它嵌套在详情页 tab 的 AnimatePresence 内，
          exit 动画会互相阻塞导致 tab 切换卡死 */}
      {status === "done" && imageUrl ? (
          <motion.div
            key="image"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="h-full w-full"
          >
            <img
              src={imageUrl}
              alt={`${plan.name} 效果图`}
              className="h-full w-full object-cover"
            />
            <span className="absolute top-3 left-3 inline-flex items-center gap-1 rounded-full bg-white/85 px-2.5 py-1 text-xs font-medium text-sage-700 backdrop-blur">
              <Sparkles className="h-3 w-3" />
              AI 效果图 · {mode === "controlnet" ? "基于你的户型" : "AI 生成"}
            </span>
            <button
              type="button"
              onClick={run}
              className="absolute right-3 bottom-3 inline-flex items-center gap-1 rounded-full bg-white/85 px-3 py-1.5 text-xs font-medium text-stone-600 backdrop-blur transition-colors hover:text-sage-700"
            >
              <RefreshCw className="h-3 w-3" />
              换一张
            </button>
          </motion.div>
        ) : status === "loading" ? (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex h-full flex-col items-center justify-center gap-4 bg-stone-900/10 backdrop-blur-sm"
          >
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/80 text-sage-600">
              <Sparkles className="h-6 w-6 animate-pulse" />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="typing-dot" />
              <span className="typing-dot" />
              <span className="typing-dot" />
            </div>
            <p className="px-6 text-center text-sm font-medium text-stone-600">
              {loadingLines[lineIndex]}
            </p>
          </motion.div>
        ) : (
          <motion.div
            key="idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex h-full flex-col items-center justify-center gap-3 text-center"
          >
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/70 text-wood-600">
              {status === "error" ? (
                <TriangleAlert className="h-6 w-6" />
              ) : (
                <ImageIcon className="h-6 w-6" strokeWidth={1.5} />
              )}
            </div>
            <div>
              <p className="text-sm font-semibold text-stone-700">
                {status === "error" ? "效果图生成失败" : "生成这套方案的效果图"}
              </p>
              <p className="mt-1 px-6 text-xs text-stone-500">
                {status === "error"
                  ? "请确认后端 SD 服务已启动，稍后重试"
                  : "AI 会锁住你的户型结构，渲染出真实效果图（约 10-15 秒）"}
              </p>
            </div>
            <button
              type="button"
              onClick={run}
              className="inline-flex items-center gap-1.5 rounded-xl bg-sage-600 px-4 py-2 text-sm font-medium text-white shadow-card transition-colors hover:bg-sage-700"
            >
              <Sparkles className="h-4 w-4" />
              {status === "error" ? "重试" : "生成效果图"}
            </button>
          </motion.div>
        )}
    </div>
  );
}
