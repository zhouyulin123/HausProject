import type { SceneDocument } from "@/types/scene";

const MAX_HISTORY_LENGTH = 50;

export interface SceneHistory {
  past: SceneDocument[];
  present: SceneDocument;
  future: SceneDocument[];
  changeId: number;
  canUndo: boolean;
  canRedo: boolean;
}

function withAvailability(
  history: Omit<SceneHistory, "canUndo" | "canRedo">,
): SceneHistory {
  return {
    ...history,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
  };
}

function areScenesEqual(
  first: SceneDocument,
  second: SceneDocument,
): boolean {
  return first === second || JSON.stringify(first) === JSON.stringify(second);
}

export function createSceneHistory(scene: SceneDocument): SceneHistory {
  return withAvailability({
    past: [],
    present: scene,
    future: [],
    changeId: 0,
  });
}

export function commitScene(
  history: SceneHistory,
  scene: SceneDocument,
): SceneHistory {
  if (areScenesEqual(history.present, scene)) return history;
  return withAvailability({
    past: [...history.past, history.present].slice(-MAX_HISTORY_LENGTH),
    present: scene,
    future: [],
    changeId: history.changeId + 1,
  });
}

export function undoScene(history: SceneHistory): SceneHistory {
  const previous = history.past.at(-1);
  if (!previous) return history;
  return withAvailability({
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
    changeId: history.changeId + 1,
  });
}

export function redoScene(history: SceneHistory): SceneHistory {
  const [next, ...remainingFuture] = history.future;
  if (!next) return history;
  return withAvailability({
    past: [...history.past, history.present].slice(-MAX_HISTORY_LENGTH),
    present: next,
    future: remainingFuture,
    changeId: history.changeId + 1,
  });
}

export function replaceScene(
  _history: SceneHistory,
  scene: SceneDocument,
): SceneHistory {
  return createSceneHistory(scene);
}
