export type SceneSyncState =
  | "loading"
  | "demo"
  | "saved"
  | "dirty"
  | "saving"
  | "conflict"
  | "offline";

export interface SceneReference {
  id: number;
  version: number;
}

interface SceneEditingState {
  syncState: SceneSyncState;
  sceneReference: SceneReference | null;
}

export function isSceneEditingBlocked(state: SceneEditingState): boolean {
  return state.syncState === "loading"
    || (state.syncState === "offline" && state.sceneReference === null);
}

export function sceneSyncPresentation(state: SceneEditingState): {
  label: string;
  retryable: boolean;
} {
  if (state.syncState === "offline" && state.sceneReference === null) {
    return {
      label: "场景恢复失败 · 点击重试",
      retryable: true,
    };
  }
  const labels: Record<SceneSyncState, string> = {
    loading: "正在恢复云端场景",
    demo: "本地演示 · 不会保存",
    saved: "已保存到方案",
    dirty: "等待自动保存",
    saving: "正在自动保存",
    conflict: "版本冲突 · 点击恢复",
    offline: "本地编辑 · 暂未同步",
  };
  return {
    label: labels[state.syncState],
    retryable: state.syncState === "conflict",
  };
}

export function agentTurnSceneContext(
  sceneId: number | null | undefined,
  sceneVersion: number | null | undefined,
): { scene_id: number | null; base_scene_version: number | null } {
  if (!sceneId || !sceneVersion) {
    return { scene_id: null, base_scene_version: null };
  }
  return {
    scene_id: sceneId,
    base_scene_version: sceneVersion,
  };
}
