import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  fetchDesignScene,
  loadOrCreateDesignScene,
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

interface UseSceneEditorResult {
  history: SceneHistory;
  selectedItemId: string | null;
  transformMode: TransformMode;
  syncState: SceneSyncState;
  validation: SceneValidationReport | null;
  selectItem: (instanceId: string | null) => void;
  setTransformMode: (mode: TransformMode) => void;
  commitTransform: (instanceId: string, transform: SceneTransform) => void;
  nudgeSelected: (x: number, z: number) => void;
  rotateSelected: (radians?: number) => void;
  undo: () => void;
  redo: () => void;
  reload: () => Promise<void>;
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

  const sceneIdRef = useRef<number | null>(null);
  const serverVersionRef = useRef<number | null>(null);
  const historyRef = useRef(history);
  const lastSavedChangeIdRef = useRef(0);
  const saveInFlightRef = useRef(false);

  useEffect(() => {
    historyRef.current = history;
  }, [history]);

  useEffect(() => {
    let cancelled = false;
    setSelectedItemId(null);
    sceneIdRef.current = null;
    serverVersionRef.current = null;
    lastSavedChangeIdRef.current = 0;
    setValidation(null);
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
    const sceneId = sceneIdRef.current;
    const baseVersion = serverVersionRef.current;
    const currentHistory = historyRef.current;
    if (
      !sceneId ||
      !baseVersion ||
      saveInFlightRef.current ||
      currentHistory.changeId === lastSavedChangeIdRef.current
    ) {
      return;
    }

    const savingChangeId = currentHistory.changeId;
    saveInFlightRef.current = true;
    setSyncState("saving");
    let shouldFlushAgain = false;
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
      setSyncState(shouldFlushAgain ? "dirty" : "saved");
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setSyncState("conflict");
      } else {
        console.warn("[SceneEditor] 场景自动保存失败", error);
        setSyncState("offline");
      }
    } finally {
      saveInFlightRef.current = false;
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
    setHistory((current) => undoScene(current));
  }, []);

  const redo = useCallback(() => {
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

  return {
    history,
    selectedItemId,
    transformMode,
    syncState,
    validation,
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
  };
}
