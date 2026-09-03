import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ImageIcon, RefreshCw, Sparkles, TriangleAlert, X } from "lucide-react";
import {
  cancelEffectRender,
  fetchEffectRender,
  fetchLatestEffectRender,
  queueEffectRender,
} from "@/api/designApi";
import type { EffectRenderJob } from "@/api/designApi";
import type { DesignPlan } from "@/types/design";

type Status = "idle" | "loading" | "done" | "error" | "cancelled";

const loadingLines = [
  "AI 正在绘制效果图...",
  "正在锁定户型结构、铺陈家具...",
  "正在渲染灯光与材质质感...",
];

function clientRenderKey(planVersionId: number): string {
  const nonce = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `effect:${planVersionId}:${nonce}`;
}

export function visibleEffectRenderStatus(job: EffectRenderJob): Status {
  if (job.status === "completed" && job.imageUrl) return "done";
  if (job.status === "queued" || job.status === "running") return "loading";
  if (job.status === "cancelled") return "cancelled";
  return "error";
}

export function effectRenderFailureMessage(job: EffectRenderJob | null): string {
  if (job?.status === "provider_unavailable") return "效果图服务暂不可用，请稍后重试";
  if (job?.status === "dead_letter") return "任务重试已耗尽，请重新发起";
  if (job?.status === "cancelled") return "效果图任务已取消";
  return job?.errorMessage || "效果图生成失败，请稍后重试";
}

/** 方案主效果图：任务由独立 Worker 执行，组件重挂载时恢复服务端状态。 */
export default function EffectImage({ plan }: { plan: DesignPlan }) {
  const [status, setStatus] = useState<Status>("idle");
  const [job, setJob] = useState<EffectRenderJob | null>(null);
  const [lineIndex, setLineIndex] = useState(0);
  const enqueueingRef = useRef(false);
  const idempotencyKeyRef = useRef<string | null>(null);

  const applyJob = useCallback((next: EffectRenderJob) => {
    setJob(next);
    setStatus(visibleEffectRenderStatus(next));
  }, []);

  useEffect(() => {
    let active = true;
    setJob(null);
    setStatus("idle");
    if (!plan.planVersionId) return () => { active = false; };
    fetchLatestEffectRender(plan.planVersionId)
      .then((restored) => {
        if (!active || !restored) return;
        applyJob(restored);
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => { active = false; };
  }, [applyJob, plan.planVersionId]);

  useEffect(() => {
    if (status !== "loading" || !job) return;
    const timer = window.setInterval(() => {
      fetchEffectRender(job.jobId)
        .then(applyJob)
        .catch(() => setStatus("error"));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [applyJob, job, status]);

  useEffect(() => {
    if (status !== "loading") return;
    const timer = window.setInterval(
      () => setLineIndex((index) => (index + 1) % loadingLines.length),
      2500,
    );
    return () => window.clearInterval(timer);
  }, [status]);

  const run = async (newVariation = false) => {
    if (enqueueingRef.current) return;
    enqueueingRef.current = true;
    setStatus("loading");
    setLineIndex(0);
    try {
      if (!plan.planVersionId) {
        throw new Error("当前方案没有可追溯的服务端版本");
      }
      if (newVariation || !idempotencyKeyRef.current) {
        idempotencyKeyRef.current = clientRenderKey(plan.planVersionId);
      }
      applyJob(
        await queueEffectRender(
          plan.planVersionId,
          idempotencyKeyRef.current,
        ),
      );
    } catch {
      setStatus("error");
    } finally {
      enqueueingRef.current = false;
    }
  };

  const cancel = async () => {
    if (!job) return;
    try {
      applyJob(await cancelEffectRender(job.jobId));
    } catch {
      setStatus("error");
    }
  };

  return (
    <div className={`relative h-64 overflow-hidden rounded-3xl ${plan.coverGradient}`}>
      {status === "done" && job?.imageUrl ? (
        <motion.div
          key="image"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="h-full w-full"
        >
          <img
            src={job.imageUrl}
            alt={`${plan.name} 效果图`}
            className="h-full w-full object-cover"
          />
          <span className="absolute top-3 left-3 inline-flex items-center gap-1 rounded-full bg-white/85 px-2.5 py-1 text-xs font-medium text-sage-700 backdrop-blur">
            <Sparkles className="h-3 w-3" />
            AI 效果图 · {job.mode === "controlnet" ? "基于你的户型" : "AI 生成"}
          </span>
          <button
            type="button"
            onClick={() => run(true)}
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
          <p className="px-6 text-center text-sm font-medium text-stone-600">
            {loadingLines[lineIndex]} {job ? `${job.progress}%` : ""}
          </p>
          {job && (
            <button
              type="button"
              onClick={cancel}
              className="inline-flex items-center gap-1 text-xs font-medium text-stone-600 hover:text-stone-900"
            >
              <X className="h-3.5 w-3.5" />
              取消任务
            </button>
          )}
        </motion.div>
      ) : (
        <motion.div
          key="idle"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-full flex-col items-center justify-center gap-3 text-center"
        >
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/70 text-wood-600">
            {status === "error" || status === "cancelled" ? (
              <TriangleAlert className="h-6 w-6" />
            ) : (
              <ImageIcon className="h-6 w-6" strokeWidth={1.5} />
            )}
          </div>
          <div>
            <p className="text-sm font-semibold text-stone-700">
              {status === "idle" ? "生成这套方案的效果图" : effectRenderFailureMessage(job)}
            </p>
            {status === "idle" && (
              <p className="mt-1 px-6 text-xs text-stone-500">
                AI 会结合当前户型和方案生成效果图
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => run(status !== "idle")}
            className="inline-flex items-center gap-1.5 rounded-xl bg-sage-600 px-4 py-2 text-sm font-medium text-white shadow-card transition-colors hover:bg-sage-700"
          >
            <Sparkles className="h-4 w-4" />
            {status === "idle" ? "生成效果图" : "重新生成"}
          </button>
        </motion.div>
      )}
    </div>
  );
}
