import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createBlenderRenderJob,
  fetchDesignScene,
  fetchBlenderRenderJob,
  loadOrCreateDesignScene,
  runSceneAgentCommand,
  updateDesignScene,
} from "@/api/designApi";
import {
  buildSceneDocument,
  clampItemTransform,
  isDemoScene,
  updateSceneItemTransform,
} from "@/lib/sceneDocument";
import {
  commitScene,
  createSceneHistory,
  redoScene,
  replaceScene,
  undoScene,
  type SceneHistory,
} from "@/lib/sceneHistory";
import type { DesignPlan } from "@/types/design";
import type {
  BlenderRenderJob,
  BlenderRenderProfile,
  SceneTransform,
  SceneValidationReport,
} from "@/types/scene";

const AUTO_SAVE_DELAY_MS = 800;
const KEYBOARD_NUDGE_METERS = 0.1;
const ROTATION_STEP_RADIANS = Math.PI / 12;

export type TransformMode = "translate" | "rotate";
export type SceneSyncState =
  | "loading"
  | "demo"
  | "saved"
  | "dirty"
  | "saving"
  | "conflict"
  | "offline";
export type SceneAgentState = "idle" | "thinking" | "done" | "blocked" | "error";

interface UseSceneEditorResult {
  history: SceneHistory;
  selectedItemId: string | null;
  transformMode: TransformMode;
  syncState: SceneSyncState;
  validation: SceneValidationReport | null;
  sceneAgentState: SceneAgentState;
  sceneAgentMessage: string;
  blenderRenderJob: BlenderRenderJob | null;
  blenderRenderMessage: string;
  blenderRenderPending: boolean;
  selectItem: (instanceId: string | null) => void;
  setTransformMode: (mode: TransformMode) => void;
  commitTransform: (instanceId: string, transform: SceneTransform) => void;
  nudgeSelected: (x: number, z: number) => void;
  rotateSelected: (radians?: number) => void;
  undo: () => void;
  redo: () => void;
  reload: () => Promise<void>;
  runSceneAgent: (instruction: string) => Promise<void>;
  queueBlenderRender: (profile: BlenderRenderProfile) => Promise<void>;
}

export function useSceneEditor(
  plan: DesignPlan,
  roomType: string,
): UseSceneEditorResult {
  const initialScene = useMemo(
    () => buildSceneDocument(plan, roomType),
    [plan, roomType],
  );
  const [history, setHistory] = useState(() =>
    createSceneHistory(initialScene),
  );
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [transformMode, setTransformMode] =
    useState<TransformMode>("translate");
  const [syncState, setSyncState] = useState<SceneSyncState>(
    plan.planVersionId ? "loading" : "demo",
  );
  const [validation, setValidation] =
    useState<SceneValidationReport | null>(null);
  const [sceneAgentState, setSceneAgentState] =
    useState<SceneAgentState>("idle");
  const [sceneAgentMessage, setSceneAgentMessage] = useState("");
  const [blenderRenderJob, setBlenderRenderJob] =
    useState<BlenderRenderJob | null>(null);
  const [blenderRenderMessage, setBlenderRenderMessage] = useState("");
  const [blenderRenderPending, setBlenderRenderPending] = useState(false);

  const sceneIdRef = useRef<number | null>(null);
  const serverVersionRef = useRef<number | null>(null);
  const historyRef = useRef(history);
  const syncStateRef = useRef(syncState);
  const sceneAgentStateRef = useRef<SceneAgentState>("idle");
  const sceneAgentRunInFlightRef = useRef(false);
  const blenderRenderInFlightRef = useRef(false);
  const lastSavedChangeIdRef = useRef(0);
  const savePromiseRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    historyRef.current = history;
  }, [history]);

  useEffect(() => {
    syncStateRef.current = syncState;
  }, [syncState]);

  useEffect(() => {
    let cancelled = false;
    setSelectedItemId(null);
    sceneIdRef.current = null;
    serverVersionRef.current = null;
    lastSavedChangeIdRef.current = 0;
    setValidation(null);
    setSceneAgentState("idle");
    setSceneAgentMessage("");
    setBlenderRenderJob(null);
    setBlenderRenderMessage("");
    setBlenderRenderPending(false);
    setHistory((current) => replaceScene(current, initialScene));

    if (!plan.planVersionId || isDemoScene(initialScene)) {
      setSyncState("demo");
      return () => {
        cancelled = true;
      };
    }

    setSyncState("loading");
    void loadOrCreateDesignScene(plan.planVersionId, initialScene)
      .then((loaded) => {
        if (cancelled) return;
        sceneIdRef.current = loaded.id;
        serverVersionRef.current = loaded.current_version;
        lastSavedChangeIdRef.current = 0;
        setValidation(loaded.validation);
        setHistory((current) => replaceScene(current, loaded.scene));
        setSyncState("saved");
      })
      .catch((error) => {
        if (cancelled) return;
        console.warn("[SceneEditor] 场景恢复失败，进入本地预览", error);
        setSyncState("offline");
      });

    return () => {
      cancelled = true;
    };
  }, [initialScene, plan.planVersionId]);

  const flushSave = useCallback(async (): Promise<void> => {
    if (savePromiseRef.current) {
      await savePromiseRef.current;
      return flushSave();
    }
    const sceneId = sceneIdRef.current;
    const baseVersion = serverVersionRef.current;
    const currentHistory = historyRef.current;
    if (
      !sceneId ||
      !baseVersion ||
      currentHistory.changeId === lastSavedChangeIdRef.current
    ) {
      return;
    }

    const savingChangeId = currentHistory.changeId;
    syncStateRef.current = "saving";
    setSyncState("saving");
    let shouldFlushAgain = false;
    const savePromise = (async () => {
      try {
        const saved = await updateDesignScene(
          sceneId,
          baseVersion,
          currentHistory.present,
        );
        serverVersionRef.current = saved.current_version;
        lastSavedChangeIdRef.current = savingChangeId;
        setValidation(saved.validation);
        shouldFlushAgain =
          historyRef.current.changeId !== lastSavedChangeIdRef.current;
        syncStateRef.current = shouldFlushAgain ? "dirty" : "saved";
        setSyncState(syncStateRef.current);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          syncStateRef.current = "conflict";
          setSyncState("conflict");
        } else {
          console.warn("[SceneEditor] 场景自动保存失败", error);
          syncStateRef.current = "offline";
          setSyncState("offline");
        }
      }
    })();
    savePromiseRef.current = savePromise;
    await savePromise;
    if (savePromiseRef.current === savePromise) {
      savePromiseRef.current = null;
    }

    if (shouldFlushAgain) {
      await flushSave();
    }
  }, []);

  useEffect(() => {
    if (
      history.changeId === lastSavedChangeIdRef.current ||
      !sceneIdRef.current ||
      syncState === "conflict"
    ) {
      return;
    }
    setSyncState("dirty");
    const timer = window.setTimeout(() => {
      void flushSave();
    }, AUTO_SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [flushSave, history.changeId, syncState]);

  const commitTransform = useCallback(
    (instanceId: string, transform: SceneTransform) => {
      if (
        sceneAgentStateRef.current === "thinking" ||
        blenderRenderInFlightRef.current
      ) {
        return;
      }
      setHistory((current) => {
        const item = current.present.items.find(
          (candidate) => candidate.instanceId === instanceId,
        );
        if (!item) return current;
        const constrained = clampItemTransform(
          current.present,
          item,
          transform,
        );
        return commitScene(
          current,
          updateSceneItemTransform(
            current.present,
            instanceId,
            constrained,
          ),
        );
      });
    },
    [],
  );

  const nudgeSelected = useCallback(
    (x: number, z: number) => {
      if (!selectedItemId) return;
      const item = historyRef.current.present.items.find(
        (candidate) => candidate.instanceId === selectedItemId,
      );
      if (!item) return;
      commitTransform(selectedItemId, {
        ...item.transform,
        position: {
          ...item.transform.position,
          x: item.transform.position.x + x,
          z: item.transform.position.z + z,
        },
      });
    },
    [commitTransform, selectedItemId],
  );

  const rotateSelected = useCallback(
    (radians = ROTATION_STEP_RADIANS) => {
      if (!selectedItemId) return;
      const item = historyRef.current.present.items.find(
        (candidate) => candidate.instanceId === selectedItemId,
      );
      if (!item) return;
      commitTransform(selectedItemId, {
        ...item.transform,
        rotation: {
          ...item.transform.rotation,
          y: item.transform.rotation.y + radians,
        },
      });
    },
    [commitTransform, selectedItemId],
  );

  const undo = useCallback(() => {
    if (
      sceneAgentStateRef.current === "thinking" ||
      blenderRenderInFlightRef.current
    ) {
      return;
    }
    setHistory((current) => undoScene(current));
  }, []);

  const redo = useCallback(() => {
    if (
      sceneAgentStateRef.current === "thinking" ||
      blenderRenderInFlightRef.current
    ) {
      return;
    }
    setHistory((current) => redoScene(current));
  }, []);

  const reload = useCallback(async () => {
    const sceneId = sceneIdRef.current;
    if (!sceneId) return;
    setSyncState("loading");
    try {
      const loaded = await fetchDesignScene(sceneId);
      serverVersionRef.current = loaded.current_version;
      lastSavedChangeIdRef.current = 0;
      setValidation(loaded.validation);
      setHistory((current) => replaceScene(current, loaded.scene));
      setSyncState("saved");
    } catch (error) {
      console.warn("[SceneEditor] 场景重新载入失败", error);
      setSyncState("offline");
    }
  }, []);

  const runSceneAgent = useCallback(
    async (instruction: string) => {
      if (!instruction.trim()) return;
      if (sceneAgentRunInFlightRef.current) return;
      if (!sceneIdRef.current || !serverVersionRef.current) {
        setSceneAgentState("error");
        setSceneAgentMessage("演示方案暂不写入云端，请先生成一套正式方案");
        return;
      }
      sceneAgentRunInFlightRef.current = true;
      sceneAgentStateRef.current = "thinking";
      setSceneAgentState("thinking");
      setSceneAgentMessage("正在保存当前修改并理解指令…");
      await flushSave();
      if (["conflict", "offline"].includes(syncStateRef.current)) {
        sceneAgentRunInFlightRef.current = false;
        sceneAgentStateRef.current = "idle";
        setSceneAgentState("error");
        setSceneAgentMessage("当前修改尚未同步，请恢复连接或刷新场景后重试");
        return;
      }
      const sceneId = sceneIdRef.current;
      const baseVersion = serverVersionRef.current;
      const startingChangeId = historyRef.current.changeId;
      setSceneAgentMessage("正在理解指令并检查空间约束…");
      try {
        const result = await runSceneAgentCommand(
          sceneId,
          baseVersion,
          instruction.trim(),
        );
        if (historyRef.current.changeId !== startingChangeId) {
          syncStateRef.current = "conflict";
          setSyncState("conflict");
          setSceneAgentState("blocked");
          setSceneAgentMessage("AI 执行期间场景发生了本地修改，请恢复最新版本后重试");
          return;
        }
        serverVersionRef.current = result.scene.current_version;
        lastSavedChangeIdRef.current = 0;
        setValidation(result.scene.validation);
        setSelectedItemId(null);
        setHistory((current) => replaceScene(current, result.scene.scene));
        syncStateRef.current = "saved";
        setSyncState("saved");
        setSceneAgentState("done");
        setSceneAgentMessage(result.message);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setSyncState("conflict");
          setSceneAgentState("blocked");
          setSceneAgentMessage("场景已在其他页面更新，请恢复最新版本后重试");
        } else if (error instanceof ApiError && error.status === 422) {
          setSceneAgentState("blocked");
          setSceneAgentMessage("这项调整会造成碰撞、越界或堵塞动线，未写入场景");
        } else if (error instanceof ApiError && error.status === 429) {
          setSceneAgentState("blocked");
          setSceneAgentMessage("操作过于频繁，请稍等一分钟后再试");
        } else {
          setSceneAgentState("error");
          setSceneAgentMessage("Scene Agent 暂时不可用，请稍后再试");
        }
      } finally {
        sceneAgentRunInFlightRef.current = false;
        sceneAgentStateRef.current = "idle";
      }
    },
    [flushSave],
  );

  useEffect(() => {
    const sceneId = sceneIdRef.current;
    const job = blenderRenderJob;
    if (
      !sceneId ||
      !job ||
      !["queued", "running"].includes(job.status)
    ) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;

    const poll = async () => {
      try {
        const refreshed = await fetchBlenderRenderJob(sceneId, job.id);
        if (cancelled) return;
        setBlenderRenderJob(refreshed);
        if (refreshed.status === "completed") {
          setBlenderRenderMessage(
            `场景版本 ${refreshed.scene_version} 的高质量效果图已完成`,
          );
        } else if (refreshed.status === "failed") {
          setBlenderRenderMessage(
            refreshed.error_message ?? "高质量渲染失败，请稍后重试",
          );
        } else {
          setBlenderRenderMessage(
            refreshed.status === "running"
              ? `Blender 正在渲染，进度 ${refreshed.progress}%`
              : "渲染任务已排队，等待独立 Worker",
          );
          timer = window.setTimeout(poll, 2000);
        }
      } catch (error) {
        if (cancelled) return;
        console.warn("[SceneEditor] Blender 渲染状态查询失败", error);
        setBlenderRenderMessage("暂时无法获取渲染进度，正在自动重试");
        timer = window.setTimeout(poll, 5000);
      }
    };
    timer = window.setTimeout(poll, 1200);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [blenderRenderJob?.id, blenderRenderJob?.status]);

  const queueBlenderRender = useCallback(
    async (profile: BlenderRenderProfile) => {
      if (
        blenderRenderInFlightRef.current ||
        sceneAgentRunInFlightRef.current ||
        ["queued", "running"].includes(blenderRenderJob?.status ?? "")
      ) {
        return;
      }
      if (!sceneIdRef.current || !serverVersionRef.current) {
        setBlenderRenderMessage("演示方案不能提交高质量渲染任务");
        return;
      }
      blenderRenderInFlightRef.current = true;
      setBlenderRenderPending(true);
      setBlenderRenderMessage("正在保存场景并创建隔离渲染任务…");
      await flushSave();
      if (["conflict", "offline"].includes(syncStateRef.current)) {
        blenderRenderInFlightRef.current = false;
        setBlenderRenderPending(false);
        setBlenderRenderMessage("当前场景尚未同步，请恢复连接后再渲染");
        return;
      }
      try {
        const job = await createBlenderRenderJob(
          sceneIdRef.current,
          serverVersionRef.current,
          profile,
        );
        setBlenderRenderJob(job);
        setBlenderRenderMessage(
          job.status === "completed"
            ? `场景版本 ${job.scene_version} 的效果图已存在`
            : "渲染任务已排队，等待独立 Blender Worker",
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          syncStateRef.current = "conflict";
          setSyncState("conflict");
          setBlenderRenderMessage("场景版本已经变化，请恢复最新版本后重试");
        } else if (error instanceof ApiError && error.status === 429) {
          setBlenderRenderMessage("高质量渲染请求过于频繁，请稍后再试");
        } else {
          setBlenderRenderMessage("暂时无法创建高质量渲染任务");
        }
      } finally {
        blenderRenderInFlightRef.current = false;
        setBlenderRenderPending(false);
      }
    },
    [blenderRenderJob?.status, flushSave],
  );

  return {
    history,
    selectedItemId,
    transformMode,
    syncState,
    validation,
    sceneAgentState,
    sceneAgentMessage,
    blenderRenderJob,
    blenderRenderMessage,
    blenderRenderPending,
    selectItem: setSelectedItemId,
    setTransformMode,
    commitTransform,
    nudgeSelected: (x, z) =>
      nudgeSelected(
        x * KEYBOARD_NUDGE_METERS,
        z * KEYBOARD_NUDGE_METERS,
      ),
    rotateSelected,
    undo,
    redo,
    reload,
    runSceneAgent,
    queueBlenderRender,
  };
}
