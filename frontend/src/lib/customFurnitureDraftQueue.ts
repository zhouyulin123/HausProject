import type { AgentSceneReference } from "@/types/agent";
import type {
  CustomFurnitureSpec,
  CustomFurnitureSpecPatch,
} from "@/types/customFurniture";

export interface CustomFurnitureDraftConflictState {
  stateVersion: number;
  customFurnitureDraft: CustomFurnitureSpecPatch | null;
  sceneRef: AgentSceneReference | null;
}

export class CustomFurnitureDraftConflictError extends Error {
  constructor(readonly conflict: CustomFurnitureDraftConflictState) {
    super("定制家具草稿状态版本冲突");
  }
}

interface DraftSavePayload {
  clientMutationId: string;
  baseStateVersion: number;
  spec: CustomFurnitureSpec;
}

interface DraftSaveResult {
  state_version: number;
}

interface DraftSyncResult {
  stateVersion: number;
  spec: CustomFurnitureSpec;
}

interface DraftSyncError {
  retryable: boolean;
}

interface CoordinatorOptions {
  initialStateVersion: number;
  debounceMs?: number;
  maxConflictRetries?: number;
  createMutationId: () => string;
  save: (payload: DraftSavePayload) => Promise<DraftSaveResult>;
  onSynced: (result: DraftSyncResult) => void;
  onError: (error: DraftSyncError) => void;
}

interface DraftJob {
  sequence: number;
  signature: string;
  spec: CustomFurnitureSpec;
  mutationId?: string;
  baseStateVersion?: number;
}

function cloneSpec(spec: CustomFurnitureSpec): CustomFurnitureSpec {
  return JSON.parse(JSON.stringify(spec)) as CustomFurnitureSpec;
}

function signatureOf(spec: CustomFurnitureSpecPatch | null): string | null {
  return spec === null ? null : JSON.stringify(spec);
}

export function createCustomFurnitureDraftSaveCoordinator(
  options: CoordinatorOptions,
) {
  const debounceMs = options.debounceMs ?? 600;
  const maxConflictRetries = options.maxConflictRetries ?? 2;
  let stateVersion = options.initialStateVersion;
  let latestSequence = 0;
  let latestSpec: CustomFurnitureSpec | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let queue: Promise<void> = Promise.resolve();
  let failedJob: DraftJob | null = null;
  let disposed = false;

  const isCurrent = (job: DraftJob) =>
    !disposed && job.sequence === latestSequence && job.signature === signatureOf(latestSpec);

  const run = async (job: DraftJob) => {
    if (!isCurrent(job)) return;
    let conflictRetries = 0;
    let mutationId = job.mutationId ?? options.createMutationId();
    let baseStateVersion = job.baseStateVersion ?? stateVersion;

    while (isCurrent(job)) {
      try {
        const saved = await options.save({
          clientMutationId: mutationId,
          baseStateVersion,
          spec: cloneSpec(job.spec),
        });
        stateVersion = Math.max(stateVersion, saved.state_version);
        failedJob = null;
        if (isCurrent(job)) {
          options.onSynced({ stateVersion, spec: cloneSpec(job.spec) });
        }
        return;
      } catch (error) {
        if (!isCurrent(job)) return;
        if (error instanceof CustomFurnitureDraftConflictError) {
          const { conflict } = error;
          stateVersion = Math.max(stateVersion, conflict.stateVersion);
          if (signatureOf(conflict.customFurnitureDraft) === job.signature) {
            failedJob = null;
            options.onSynced({ stateVersion, spec: cloneSpec(job.spec) });
            return;
          }
          if (conflictRetries >= maxConflictRetries) {
            failedJob = {
              ...job,
              mutationId,
              baseStateVersion,
            };
            options.onError({ retryable: true });
            return;
          }
          conflictRetries += 1;
          mutationId = options.createMutationId();
          baseStateVersion = conflict.stateVersion;
          continue;
        }
        failedJob = {
          ...job,
          mutationId,
          baseStateVersion,
        };
        options.onError({ retryable: true });
        return;
      }
    }
  };

  const enqueue = (job: DraftJob) => {
    queue = queue.catch(() => undefined).then(() => run(job));
  };

  const schedule = (spec: CustomFurnitureSpec) => {
    latestSequence += 1;
    latestSpec = cloneSpec(spec);
    failedJob = null;
    if (timer !== null) clearTimeout(timer);
    const job: DraftJob = {
      sequence: latestSequence,
      signature: signatureOf(latestSpec) ?? "",
      spec: cloneSpec(spec),
    };
    timer = setTimeout(() => {
      timer = null;
      enqueue(job);
    }, debounceMs);
  };

  const retryLatest = () => {
    if (!failedJob || !latestSpec || disposed) return;
    latestSequence += 1;
    const retry = {
      ...failedJob,
      sequence: latestSequence,
      spec: cloneSpec(latestSpec),
      signature: signatureOf(latestSpec) ?? "",
    };
    failedJob = null;
    enqueue(retry);
  };

  return {
    schedule,
    retryLatest,
    updateStateVersion(next: number) {
      stateVersion = Math.max(stateVersion, next);
    },
    dispose() {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
    },
  };
}
