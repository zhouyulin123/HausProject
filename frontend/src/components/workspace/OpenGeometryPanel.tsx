import { useEffect, useMemo, useRef, useState } from "react";
import { Box, CornerUpLeft, Loader2 } from "lucide-react";
import {
  addOpenGeometryToScene,
  ApiError,
  fetchDesignAgentState,
  fetchDesignScene,
  restoreOpenGeometryVersion,
  type DesignAgentStateResponse,
} from "@/api/designApi";
import type { OpenGeometryState } from "@/types/openGeometry";
import type { AgentSceneReference } from "@/types/agent";
import type { DesignScene } from "@/types/scene";
import {
  buildOpenGeometryPlacementRequest,
  openGeometryDefaultPlacement,
  resolveOpenGeometryPlacementRefresh,
} from "@/lib/openGeometryScene";


function mutationId(taskId: number) {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? `open-${taskId}-${crypto.randomUUID()}`
    : `open-${taskId}-${Date.now()}`;
}

export class AgentCheckpointRefreshError extends Error {
  constructor() {
    super("agent_checkpoint_refresh_failed");
    this.name = "AgentCheckpointRefreshError";
  }
}

export function openGeometryErrorMessage(error: unknown): string {
  if (error instanceof AgentCheckpointRefreshError) {
    return "撤销可能已经生效，但最新状态读取失败。请刷新页面后再继续修改。";
  }
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail) {
    const detail = error.detail as { code?: string; message?: string };
    if (detail.code === "version_conflict") return "模型版本已变化，已恢复最新状态，请重新选择撤销目标。";
    if (detail.code === "unsupported_geometry") return detail.message ?? "当前几何能力无法表达这项修改。";
    if (detail.code === "llm_unavailable") return "AI 几何设计服务暂不可用，当前模型保持不变。";
    if (error.status >= 500) return "撤销结果未确认，已尝试恢复服务端当前版本。请确认版本后再重试。";
    if (detail.message) return `${detail.message} 当前模型保持不变。`;
  }
  return "撤销结果未确认，已尝试恢复服务端当前版本。请确认版本后再重试。";
}

export function previousOpenGeometryVersion(state: OpenGeometryState) {
  return state.history.length >= 2 ? state.history[state.history.length - 2] : null;
}

interface OpenGeometryRestoreInput {
  baseVersion: number;
  targetVersion: number;
}

function restoreSignature(input: OpenGeometryRestoreInput): string {
  return `${input.baseVersion}:${input.targetVersion}`;
}

/** 网络结果未知时保留同一幂等键；版本或目标变化才创建新恢复操作。 */
export function createOpenGeometryRestoreCoordinator({
  createMutationId,
  restore,
}: {
  createMutationId: () => string;
  restore: (
    request: OpenGeometryRestoreInput & { clientMutationId: string },
  ) => Promise<OpenGeometryState>;
}) {
  let lastAttempt: { signature: string; clientMutationId: string } | null = null;
  let inFlight: { signature: string; promise: Promise<OpenGeometryState> } | null = null;

  return {
    restore(input: OpenGeometryRestoreInput): Promise<OpenGeometryState> {
      const signature = restoreSignature(input);
      if (inFlight?.signature === signature) return inFlight.promise;
      const clientMutationId = lastAttempt?.signature === signature
        ? lastAttempt.clientMutationId
        : createMutationId();
      lastAttempt = { signature, clientMutationId };
      const promise = restore({ ...input, clientMutationId })
        .then((result) => {
          if (lastAttempt?.clientMutationId === clientMutationId) lastAttempt = null;
          return result;
        })
        .finally(() => {
          if (inFlight?.promise === promise) inFlight = null;
        });
      inFlight = { signature, promise };
      return promise;
    },
  };
}

function restoreFailureNeedsCheckpoint(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return error.status === 409 || error.status >= 500;
}

export async function restoreOpenGeometryAndRefresh({
  restore,
  refresh,
  onCheckpointRefresh,
}: {
  restore: () => Promise<OpenGeometryState>;
  refresh: () => Promise<DesignAgentStateResponse>;
  onCheckpointRefresh: (checkpoint: DesignAgentStateResponse) => void;
}) {
  try {
    await restore();
  } catch (cause) {
    if (!restoreFailureNeedsCheckpoint(cause)) throw cause;
    try {
      const checkpoint = await refresh();
      onCheckpointRefresh(checkpoint);
    } catch {
      throw new AgentCheckpointRefreshError();
    }
    throw cause;
  }
  let checkpoint: DesignAgentStateResponse;
  try {
    checkpoint = await refresh();
  } catch {
    throw new AgentCheckpointRefreshError();
  }
  onCheckpointRefresh(checkpoint);
  return checkpoint;
}

export default function OpenGeometryPanel({
  taskId,
  state,
  sceneReference = null,
  authoritativeScene = null,
  onCheckpointRefresh,
  onSceneApplied,
}: {
  taskId: number;
  state: OpenGeometryState;
  sceneReference?: AgentSceneReference | null;
  authoritativeScene?: DesignScene | null;
  onCheckpointRefresh: (checkpoint: DesignAgentStateResponse) => void;
  onSceneApplied?: (scene: DesignScene) => void;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [syncBlocked, setSyncBlocked] = useState(false);
  const [error, setError] = useState("");
  const [placing, setPlacing] = useState(false);
  const [placementError, setPlacementError] = useState("");
  const defaultPlacement = useMemo(
    () => openGeometryDefaultPlacement(authoritativeScene, sceneReference),
    [authoritativeScene, sceneReference],
  );
  const [placementPosition, setPlacementPosition] = useState(
    () => defaultPlacement ?? { x: 0, z: 0 },
  );
  const placementEdited = useRef(false);
  const placementAttempt = useRef<{
    signature: string;
    clientMutationId: string;
  } | null>(null);
  const undoTarget = useMemo(
    () => previousOpenGeometryVersion(state),
    [state.history],
  );
  const restoreCoordinator = useMemo(
    () => createOpenGeometryRestoreCoordinator({
      createMutationId: () => mutationId(taskId),
      restore: (request) => restoreOpenGeometryVersion(taskId, request),
    }),
    [taskId],
  );

  useEffect(() => {
    setSyncBlocked(false);
  }, [state]);

  useEffect(() => {
    placementEdited.current = false;
    placementAttempt.current = null;
    setPlacementPosition(defaultPlacement ?? { x: 0, z: 0 });
  }, [taskId]);

  useEffect(() => {
    if (defaultPlacement) {
      if (!placementEdited.current) placementAttempt.current = null;
      setPlacementPosition((current) => resolveOpenGeometryPlacementRefresh(
        current,
        defaultPlacement,
        placementEdited.current,
      ));
    }
  }, [defaultPlacement]);

  const undo = async () => {
    if (!undoTarget || submitting) return;
    setError("");
    setSubmitting(true);
    try {
      await restoreOpenGeometryAndRefresh({
        restore: () => restoreCoordinator.restore({
          baseVersion: state.current_version,
          targetVersion: undoTarget.version,
        }),
        refresh: () => fetchDesignAgentState(taskId),
        onCheckpointRefresh,
      });
    } catch (cause) {
      if (cause instanceof AgentCheckpointRefreshError) setSyncBlocked(true);
      setError(openGeometryErrorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  };

  const placementReady = Boolean(
    state.current && sceneReference && defaultPlacement && onSceneApplied,
  );

  const placeInRoom = async () => {
    if (
      !state.current
      || !sceneReference
      || !defaultPlacement
      || !onSceneApplied
      || placing
    ) return;
    const signature = JSON.stringify([
      sceneReference.scene_id,
      sceneReference.version,
      state.current.version,
      placementPosition.x,
      placementPosition.z,
    ]);
    const clientMutationId = placementAttempt.current?.signature === signature
      ? placementAttempt.current.clientMutationId
      : mutationId(taskId);
    placementAttempt.current = { signature, clientMutationId };
    setPlacing(true);
    setPlacementError("");
    try {
      const result = await addOpenGeometryToScene(sceneReference.scene_id, {
        ...buildOpenGeometryPlacementRequest({
          sceneReference,
          clientMutationId,
          openGeometryVersion: state.current.version,
          position: placementPosition,
        }),
      });
      placementAttempt.current = null;
      onSceneApplied(result);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          onSceneApplied(await fetchDesignScene(sceneReference.scene_id));
          setPlacementError("房间已更新，已恢复最新版本，请确认落点后再次加入。");
        } catch {
          setPlacementError("房间版本冲突且恢复失败，请刷新页面后重试。");
        }
      } else if (cause instanceof ApiError && cause.status === 422) {
        const detail = cause.detail as {
          message?: string;
          issues?: Array<{ message?: string }>;
        } | null;
        setPlacementError(
          detail?.issues?.[0]?.message
            ?? detail?.message
            ?? "当前落点不满足房间边界或碰撞约束。",
        );
      } else {
        setPlacementError("加入结果未确认，可直接重试；系统会复用同一幂等请求。");
      }
    } finally {
      setPlacing(false);
    }
  };

  return (
    <section className="border border-[#293229] bg-[#171e18] p-4 text-[#e3e7df]" aria-label="开放几何家具设计">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[9px] tracking-[0.16em] text-[#7f8b81] uppercase">Open geometry</p>
          <h2 className="mt-1 text-sm font-medium !text-[#eef1ea]">对话式自由造型</h2>
        </div>
        <span className="border border-[#d5ff67]/30 px-2 py-1 font-mono text-[9px] text-[#d5ff67]">
          V{state.current_version}
        </span>
      </div>
      <p className="mt-3 text-[11px] leading-5 text-[#8f9a91]">
        请通过左侧对话创建或修改家具。校验通过后，3D 预览会自动更新。
      </p>
      {state.current && (
        <div className="mt-3 border-l-2 border-[#d5ff67] pl-3">
          <p className="text-xs text-[#edf1e9]">{state.current.design.name}</p>
          <p className="mt-1 text-[10px] text-[#7f8b81]">
            {state.current.design.parts.length} 个稳定部件 · {state.current.design.materials.length} 种材质
          </p>
        </div>
      )}
      {state.history.length > 0 && (
        <ol className="mt-3 space-y-1 border-t border-white/10 pt-3" aria-label="开放几何版本历史">
          {state.history.slice(-3).reverse().map((version) => (
            <li key={version.version} className="flex items-center justify-between gap-3 text-[10px] text-[#8f9a91]">
              <span className="truncate">{version.instruction || version.design.name}</span>
              <span className="shrink-0 font-mono">V{version.version}</span>
            </li>
          ))}
        </ol>
      )}
      <button type="button" disabled={submitting || syncBlocked || !undoTarget} onClick={() => void undo()} title="恢复上一个有效版本" aria-label="撤销开放几何修改" className="mt-4 flex h-9 w-9 items-center justify-center border border-white/15 text-[#cbd2ca] disabled:opacity-35">
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CornerUpLeft className="h-4 w-4" />}
      </button>
      {error && <p role="alert" className="mt-3 border-l-2 border-[#ff8d78] pl-3 text-[11px] leading-5 text-[#ffb4a5]">{error}</p>}
      <div
        className="mt-4 border-t border-white/10 pt-4"
        data-placement-ready={placementReady}
      >
        <div className="flex items-start gap-2">
          <Box className="mt-0.5 h-4 w-4 text-[#d5ff67]" />
          <div>
            <p className="text-xs font-medium">加入当前房间</p>
            <p className="mt-1 text-[10px] leading-4 text-[#8f9a91]">
              冻结当前有效版本并加入米制房间，可继续移动和旋转。
            </p>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {(["x", "z"] as const).map((axis) => (
            <label key={axis} className="text-[10px] text-[#8f9a91]">
              房间 {axis.toUpperCase()}（m）
              <input
                type="number"
                min={-20}
                max={20}
                step={0.1}
                value={placementPosition[axis]}
                onChange={(event) => {
                  placementEdited.current = true;
                  setPlacementPosition((current) => ({
                    ...current,
                    [axis]: Number(event.target.value),
                  }));
                }}
                className="mt-1 h-9 w-full border border-white/15 bg-[#111713] px-2 text-xs text-[#eef1ea]"
              />
            </label>
          ))}
        </div>
        <button
          type="button"
          disabled={!placementReady || placing}
          onClick={() => void placeInRoom()}
          className="mt-3 inline-flex min-h-9 w-full items-center justify-center gap-2 bg-[#d5ff67] px-3 text-xs font-medium text-[#111713] disabled:cursor-not-allowed disabled:opacity-35"
        >
          {placing && <Loader2 className="h-4 w-4 animate-spin" />}
          {placing ? "正在加入房间" : "加入当前房间"}
        </button>
        {!sceneReference && (
          <p className="mt-2 text-[10px] text-[#f1c08b]">当前没有已恢复的服务端房间场景。</p>
        )}
        {sceneReference && !defaultPlacement && (
          <p className="mt-2 text-[10px] text-[#f1c08b]">
            权威房间版本尚未同步，暂不能安全计算家具落点。
          </p>
        )}
        {placementError && (
          <p role="alert" className="mt-2 text-[10px] leading-4 text-[#ffb4a5]">
            {placementError}
          </p>
        )}
      </div>
    </section>
  );
}
