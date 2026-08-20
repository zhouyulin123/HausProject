import { motion } from "framer-motion";
import { CheckCircle2, FileImage, Lightbulb, Ruler, ScanEye, Sparkles } from "lucide-react";
import type { ImageAnalysis } from "@/types/requirement";
import LoadingAI from "@/components/chat/LoadingAI";
import Tag from "@/components/common/Tag";

export type AnalysisStatus = "waiting" | "analyzing" | "done";

const statusLabel: Record<AnalysisStatus, { text: string; tone: "cream" | "terra" | "sage" }> = {
  waiting: { text: "等待分析", tone: "cream" },
  analyzing: { text: "分析中", tone: "terra" },
  done: { text: "已完成", tone: "sage" },
};

export default function AnalysisResult({
  fileName,
  fileSize,
  status,
  analysis,
}: {
  fileName: string;
  fileSize: string;
  status: AnalysisStatus;
  analysis: ImageAnalysis | null;
}) {
  const label = statusLabel[status];

  return (
    <div className="rounded-3xl border border-cream-200 bg-white/80 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cream-200 text-wood-600">
            <FileImage className="h-5 w-5" strokeWidth={1.6} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-stone-700">{fileName}</p>
            <p className="text-xs text-stone-400">{fileSize}</p>
          </div>
        </div>
        <Tag tone={label.tone}>{label.text}</Tag>
      </div>

      {status === "analyzing" && (
        <div className="mt-4 flex items-center gap-3 rounded-2xl bg-cream-100/80 px-4 py-3">
          <LoadingAI compact />
          <span className="text-sm text-stone-500">
            AI 正在识别空间结构、采光与动线...
          </span>
        </div>
      )}

      {status === "done" && analysis && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-sage-700">
              <ScanEye className="h-4 w-4" />
              AI 空间识别结果
            </div>
            {analysis.source === "vl" && (
              <Tag tone="sage">
                <Sparkles className="h-3 w-3" />
                Qwen3-VL 视觉分析
              </Tag>
            )}
            {analysis.spaceType && analysis.spaceType !== "未知空间" && (
              <Tag tone="wood">{analysis.spaceType}</Tag>
            )}
            {analysis.roomCount && <Tag tone="cream">{analysis.roomCount}</Tag>}
          </div>

          {analysis.roomModel && (
            <div className="mt-3 rounded-2xl border border-sage-100 bg-sage-50/50 p-3.5">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-sage-700">
                <Ruler className="h-4 w-4" />
                空间结构识别
              </div>
              <p className="mt-1.5 text-xs text-stone-600">
                识别到 {analysis.roomModel.rooms.length} 个空间
                {analysis.roomModel.doors.length > 0 &&
                  ` · ${analysis.roomModel.doors.length} 扇门`}
                {analysis.roomModel.windows.length > 0 &&
                  ` · ${analysis.roomModel.windows.length} 扇窗`}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {analysis.roomModel.rooms.map((room) => (
                  <Tag key={room.id} tone="cream">
                    {room.name}
                  </Tag>
                ))}
              </div>
              {analysis.roomModel.requiresConfirmation.length > 0 && (
                <p className="mt-2 text-xs text-terra-600">
                  尺寸与门窗宽度将在下一步确认后用于生成 3D 布局
                </p>
              )}
            </div>
          )}

          <ul className="mt-3 space-y-2">
            {analysis.findings.map((finding, i) => (
              <motion.li
                key={finding}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.12 }}
                className="flex items-start gap-2 text-sm text-stone-600"
              >
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-sage-500" />
                {finding}
              </motion.li>
            ))}
          </ul>

          {analysis.suggestions && analysis.suggestions.length > 0 && (
            <div className="mt-4 rounded-2xl bg-terra-50/70 p-3.5">
              <div className="flex items-center gap-1.5 text-sm font-semibold text-terra-700">
                <Lightbulb className="h-4 w-4" />
                装修建议
              </div>
              <ul className="mt-2 space-y-1.5">
                {analysis.suggestions.map((s) => (
                  <li key={s} className="flex items-start gap-2 text-sm text-stone-600">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-terra-400" />
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
