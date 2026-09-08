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
import type { SceneSyncState } from "@/lib/sceneEditingPolicy";
import type { EffectSceneBinding } from "@/lib/effectSceneBinding";

export type { EffectSceneBinding } from "@/lib/effectSceneBinding";

type Status = "idle" | "loading" | "done" | "error" | "cancelled";

const loadingLines = [
  "AI 正在绘制效果图...",
  "正在锁定户型结构、铺陈家具...",
  "正在渲染灯光与材质质感...",
];

function clientRenderKey(
  planVersionId: number,
  sceneId: number,
  sceneVersion: number,
): string {
  const nonce = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `effect:${planVersionId}:${sceneId}:${sceneVersion}:${nonce}`;
}

export function effectRenderAvailability(binding: EffectSceneBinding): {
  ready: boolean;
  message: string;
} {
  if (
    binding.syncState === "saved"
    && binding.sceneId
    && binding.sceneVersion
  ) {
    return { ready: true, message: `场景版本 ${binding.sceneVersion} 已保存` };
  }
  const messages: Record<SceneSyncState, string> = {
    loading: "正在恢复服务端场景，请稍候",
    demo: "当前方案还没有可渲染的服务端场景",
    saved: "服务端场景引用不完整，无法生成效果图",
    dirty: "当前 3D 编辑尚未保存，请等待自动保存完成",
    saving: "当前 3D 编辑正在保存，请稍候",
    conflict: "3D 场景存在版本冲突，请先恢复最新版本",
    offline: "3D 场景尚未同步到服务端，请恢复连接",
  };
  return { ready: false, message: messages[binding.syncState] };
}

export function effectRenderMatchesScene(
  job: EffectRenderJob,
  binding: Pick<EffectSceneBinding, "sceneId" | "sceneVersion">,
): boolean {
  return job.sceneId === binding.sceneId
    && job.sceneVersion === binding.sceneVersion;
}

export function effectSceneBindingKey(binding: EffectSceneBinding): string {
  return [binding.syncState, binding.sceneId ?? "none", binding.sceneVersion ?? "none"].join(":");
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
export default function EffectImage({
  plan,
  sceneBinding,
  onRetryScene,
}: {
  plan: DesignPlan;
  sceneBinding: EffectSceneBinding;
  onRetryScene?: () => void;
}) {
  const [status, setStatus] = useState<Status>("idle");
  const [job, setJob] = useState<EffectRenderJob | null>(null);
  const [lineIndex, setLineIndex] = useState(0);
  const enqueueingRef = useRef(false);
  const idempotencyKeyRef = useRef<string | null>(null);
  const availability = effectRenderAvailability(sceneBinding);
  const sceneId = sceneBinding.sceneId;
  const sceneVersion = sceneBinding.sceneVersion;

  const applyJob = useCallback((next: EffectRenderJob) => {
    setJob(next);
    setStatus(visibleEffectRenderStatus(next));
  }, []);

  useEffect(() => {
    let active = true;
    setJob(null);
    setStatus("idle");
    idempotencyKeyRef.current = null;
    if (
      !plan.planVersionId
      || !availability.ready
      || !sceneId
      || !sceneVersion
    ) return () => { active = false; };
    fetchLatestEffectRender(
      plan.planVersionId,
      sceneId,
      sceneVersion,
    )
      .then((restored) => {
        if (
          !active
          || !restored
          || restored.sceneId !== sceneId
          || restored.sceneVersion !== sceneVersion
        ) return;
        applyJob(restored);
      })
      .catch(() => {
        if (active) setStatus("error");
      });
    return () => { active = false; };
  }, [
    applyJob,
    availability.ready,
    plan.planVersionId,
    sceneId,
    sceneVersion,
  ]);

  useEffect(() => {
    if (status !== "loading" || !job) return;
    const timer = window.setInterval(() => {
      fetchEffectRender(job.jobId)
        .then((next) => {
          if (next.sceneId !== sceneId || next.sceneVersion !== sceneVersion) {
            setStatus("error");
            return;
          }
          applyJob(next);
        })
        .catch(() => setStatus("error"));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [applyJob, job?.jobId, sceneId, sceneVersion, status]);

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
      if (
        !availability.ready
        || !sceneId
        || !sceneVersion
      ) {
        throw new Error(availability.message);
      }
      if (newVariation || !idempotencyKeyRef.current) {
        idempotencyKeyRef.current = clientRenderKey(
          plan.planVersionId,
          sceneId,
          sceneVersion,
        );
      }
      const queued = await queueEffectRender(
        plan.planVersionId,
        sceneId,
        sceneVersion,
        idempotencyKeyRef.current,
      );
      if (!effectRenderMatchesScene(queued, sceneBinding)) {
        throw new Error("效果图任务未绑定当前场景版本");
      }
      applyJob(queued);
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
                {availability.ready
                  ? `AI 将严格使用${availability.message}生成效果图`
                  : availability.message}
              </p>
            )}
          </div>
          {!availability.ready && sceneBinding.syncState === "offline" && onRetryScene ? (
            <button
              type="button"
              onClick={onRetryScene}
              className="inline-flex items-center gap-1.5 rounded-xl bg-stone-700 px-4 py-2 text-sm font-medium text-white shadow-card transition-colors hover:bg-stone-800"
            >
              <RefreshCw className="h-4 w-4" />
              重试恢复场景
            </button>
          ) : (
            <button
              type="button"
              onClick={() => run(status !== "idle")}
              disabled={!availability.ready}
              className="inline-flex items-center gap-1.5 rounded-xl bg-sage-600 px-4 py-2 text-sm font-medium text-white shadow-card transition-colors hover:bg-sage-700 disabled:cursor-not-allowed disabled:bg-stone-400 disabled:shadow-none"
            >
              <Sparkles className="h-4 w-4" />
              {status === "idle" ? "生成效果图" : "重新生成"}
            </button>
          )}
        </motion.div>
      )}
    </div>
  );
}
