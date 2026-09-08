import type {
  DesignFeedbackEventRequest,
  FeedbackAction,
  FeedbackDelivery,
  FinalSelectFeedbackEvent,
  GlbLoadFailureFeedbackEvent,
  MoveFeedbackEvent,
} from "@/types/feedback";

function positiveInteger(value: number | null | undefined): value is number {
  return Number.isInteger(value) && Number(value) > 0;
}

function cleanIdentifier(value: string | null | undefined): string | null {
  const cleaned = value?.trim();
  return cleaned ? cleaned : null;
}

function stableFeedbackHash(value: string): string {
  let hash = 0x811c9dc5;
  for (const character of value) {
    hash ^= character.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function buildGlbLoadFailureFeedbackEvent(input: {
  taskId: number;
  planVersionId: number | null | undefined;
  sceneId: number | null | undefined;
  sceneVersion: number | null | undefined;
  instanceId: string | null | undefined;
  sku: string | null | undefined;
}): GlbLoadFailureFeedbackEvent | null {
  const instanceId = cleanIdentifier(input.instanceId);
  const sku = cleanIdentifier(input.sku)?.toUpperCase() ?? null;
  if (
    !positiveInteger(input.taskId)
    || !positiveInteger(input.planVersionId)
    || !positiveInteger(input.sceneId)
    || !positiveInteger(input.sceneVersion)
    || !instanceId
    || !sku
  ) {
    return null;
  }
  const signature = [
    input.taskId,
    input.planVersionId,
    input.sceneId,
    input.sceneVersion,
    instanceId,
    sku,
  ].join(":");
  return {
    client_event_id:
      `feedback-${input.taskId}-glb_load_failed-${stableFeedbackHash(signature)}`,
    action_type: "glb_load_failed",
    plan_version_id: input.planVersionId,
    scene_id: input.sceneId,
    scene_version: input.sceneVersion,
    instance_id: instanceId,
    source_sku: sku,
  };
}

export function createFeedbackClientEventId(
  taskId: number,
  action: FeedbackAction,
  nonce?: string,
): string {
  const generated = nonce ?? (
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
  const safeNonce = generated.replace(/[^A-Za-z0-9._:-]/g, "-").slice(0, 60);
  return `feedback-${taskId}-${action}-${safeNonce}`.slice(0, 100);
}

export function createPlanMutationEventIdResolver(taskId: number) {
  let pending: { signature: string; clientEventId: string } | null = null;
  return {
    resolve(signature: string, action: "adopt" | "remove" | "replace"): string {
      if (pending?.signature === signature) return pending.clientEventId;
      const clientEventId = createFeedbackClientEventId(taskId, action);
      pending = { signature, clientEventId };
      return clientEventId;
    },
    acknowledge(signature: string): void {
      if (pending?.signature === signature) pending = null;
    },
  };
}

export function buildFurnitureFeedbackEvent(input: {
  clientEventId: string;
  selectedBeforeToggle: boolean;
  planVersionId: number | null | undefined;
  sku: string | null | undefined;
  roomId: string | null | undefined;
}): DesignFeedbackEventRequest | null {
  const sku = cleanIdentifier(input.sku);
  if (!positiveInteger(input.planVersionId) || !sku) return null;
  const roomId = cleanIdentifier(input.roomId);
  return input.selectedBeforeToggle
    ? {
        client_event_id: input.clientEventId,
        action_type: "remove",
        plan_version_id: input.planVersionId,
        source_sku: sku,
        ...(roomId ? { room_id: roomId } : {}),
      }
    : {
        client_event_id: input.clientEventId,
        action_type: "adopt",
        plan_version_id: input.planVersionId,
        target_sku: sku,
        ...(roomId ? { room_id: roomId } : {}),
      };
}

export function buildFinalSelectFeedbackEvent(
  clientEventId: string,
  planVersionId: number | null | undefined,
  satisfactionScore: number | null,
): FinalSelectFeedbackEvent | null {
  if (!positiveInteger(planVersionId)) return null;
  if (
    satisfactionScore !== null
    && !([1, 2, 3, 4, 5] as const).includes(satisfactionScore as 1 | 2 | 3 | 4 | 5)
  ) return null;
  return {
    client_event_id: clientEventId,
    action_type: "final_select",
    plan_version_id: planVersionId,
    ...(satisfactionScore === null
      ? {}
      : { satisfaction_score: satisfactionScore as 1 | 2 | 3 | 4 | 5 }),
  };
}

export function buildReplaceFeedbackEvent(input: {
  clientEventId: string;
  planVersionId: number | null | undefined;
  sourceSku: string | null | undefined;
  targetSku: string | null | undefined;
  roomId: string | null | undefined;
}): DesignFeedbackEventRequest | null {
  const sourceSku = cleanIdentifier(input.sourceSku)?.toUpperCase() ?? null;
  const targetSku = cleanIdentifier(input.targetSku)?.toUpperCase() ?? null;
  if (
    !positiveInteger(input.planVersionId)
    || !sourceSku
    || !targetSku
    || sourceSku === targetSku
  ) return null;
  const roomId = cleanIdentifier(input.roomId);
  return {
    client_event_id: input.clientEventId,
    action_type: "replace",
    plan_version_id: input.planVersionId,
    source_sku: sourceSku,
    target_sku: targetSku,
    ...(roomId ? { room_id: roomId } : {}),
  };
}

export function buildMoveFeedbackEvent(
  clientEventId: string,
  sceneId: number | null | undefined,
  sceneVersion: number | null | undefined,
  instanceId: string | null | undefined,
  roomId: string | null | undefined,
): MoveFeedbackEvent | null {
  const instance = cleanIdentifier(instanceId);
  if (!positiveInteger(sceneId) || !positiveInteger(sceneVersion) || !instance) {
    return null;
  }
  const room = cleanIdentifier(roomId);
  return {
    client_event_id: clientEventId,
    action_type: "move",
    scene_id: sceneId,
    scene_version: sceneVersion,
    instance_id: instance,
    ...(room ? { room_id: room } : {}),
  };
}

export type FeedbackDeliveryAction =
  | { type: "reset" }
  | { type: "queued"; request: DesignFeedbackEventRequest; label: string }
  | { type: "retrying"; clientEventId: string }
  | { type: "sent"; clientEventId: string; message: string }
  | { type: "failed"; clientEventId: string; message: string };

export function feedbackDeliveryReducer(
  state: FeedbackDelivery[],
  action: FeedbackDeliveryAction,
): FeedbackDelivery[] {
  if (action.type === "reset") return [];
  if (action.type === "queued") {
    const delivery: FeedbackDelivery = {
      request: action.request,
      label: action.label,
      status: "sending",
      message: "正在同步反馈…",
    };
    return [
      delivery,
      ...state.filter(
        (item) => item.request.client_event_id !== action.request.client_event_id,
      ),
    ].slice(0, 5);
  }
  return state.map((delivery) =>
    delivery.request.client_event_id === action.clientEventId
      ? {
          ...delivery,
          status: action.type === "sent"
            ? "sent"
            : action.type === "failed"
              ? "failed"
              : "sending",
          message: action.type === "retrying" ? "正在重新同步反馈…" : action.message,
        }
      : delivery,
  );
}
