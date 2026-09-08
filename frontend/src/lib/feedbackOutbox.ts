import type { DesignFeedbackEventRequest } from "@/types/feedback";
import type { FeedbackDeliveryAction } from "./workspaceFeedback";

export const FEEDBACK_OUTBOX_MAX_EVENTS = 50;
export const FEEDBACK_OUTBOX_MAX_BYTES = 64 * 1024;

const STORAGE_PREFIX = "ai-home-decor:feedback-outbox:v1";
const CLIENT_EVENT_ID_PATTERN = /^[A-Za-z0-9._:-]{1,100}$/;
const PAGE_IN_FLIGHT_EVENTS = new Set<string>();

export interface FeedbackOutboxEntry {
  request: DesignFeedbackEventRequest;
  label: string;
}

interface FeedbackOutboxEnvelope {
  version: 1;
  task_id: number;
  entries: FeedbackOutboxEntry[];
}

interface OnlineEventTarget {
  addEventListener(type: "online", listener: EventListener): void;
  removeEventListener(type: "online", listener: EventListener): void;
}

interface FeedbackOutboxOptions {
  taskId: number;
  storage: Storage | null;
  send: (taskId: number, request: DesignFeedbackEventRequest) => Promise<unknown>;
  onlineTarget?: OnlineEventTarget | null;
  onDeliveryAction?: (action: FeedbackDeliveryAction) => void;
}

const ACTION_LABELS: Record<DesignFeedbackEventRequest["action_type"], string> = {
  adopt: "家具采用",
  remove: "家具移除",
  replace: "家具替换",
  move: "家具位置调整",
  final_select: "确认当前方案",
  glb_load_failed: "GLB 加载失败",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  const keys = Object.keys(value);
  return keys.length === allowedKeys.size && keys.every((key) => allowedKeys.has(key));
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedKeys = new Set(allowed);
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isIdentifier(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.length >= 1
    && value.length <= maxLength
    && value.trim() === value;
}

function optionalRoomIsValid(value: Record<string, unknown>): boolean {
  return !("room_id" in value) || isIdentifier(value.room_id, 100);
}

function parseFeedbackRequest(value: unknown): DesignFeedbackEventRequest | null {
  if (
    !isRecord(value)
    || typeof value.client_event_id !== "string"
    || !CLIENT_EVENT_ID_PATTERN.test(value.client_event_id)
    || typeof value.action_type !== "string"
    || !optionalRoomIsValid(value)
  ) {
    return null;
  }

  const common = ["client_event_id", "action_type", "room_id"];
  switch (value.action_type) {
    case "adopt":
      if (
        !hasOnlyKeys(value, [...common, "plan_version_id", "target_sku"])
        || !isPositiveInteger(value.plan_version_id)
        || !isIdentifier(value.target_sku, 50)
      ) return null;
      break;
    case "remove":
      if (
        !hasOnlyKeys(value, [...common, "plan_version_id", "source_sku"])
        || !isPositiveInteger(value.plan_version_id)
        || !isIdentifier(value.source_sku, 50)
      ) return null;
      break;
    case "replace":
      if (
        !hasOnlyKeys(value, [...common, "plan_version_id", "source_sku", "target_sku"])
        || !isPositiveInteger(value.plan_version_id)
        || !isIdentifier(value.source_sku, 50)
        || !isIdentifier(value.target_sku, 50)
        || value.source_sku.toUpperCase() === value.target_sku.toUpperCase()
      ) return null;
      break;
    case "move":
      if (
        !hasOnlyKeys(value, [...common, "scene_id", "scene_version", "instance_id"])
        || !isPositiveInteger(value.scene_id)
        || !isPositiveInteger(value.scene_version)
        || !isIdentifier(value.instance_id, 100)
      ) return null;
      break;
    case "final_select":
      if (
        !hasOnlyKeys(value, [...common, "plan_version_id", "satisfaction_score"])
        || !isPositiveInteger(value.plan_version_id)
        || (
          "satisfaction_score" in value
          && (!Number.isInteger(value.satisfaction_score) || Number(value.satisfaction_score) < 1 || Number(value.satisfaction_score) > 5)
        )
      ) return null;
      break;
    case "glb_load_failed":
      if (
        !hasOnlyKeys(value, [
          ...common,
          "plan_version_id",
          "scene_id",
          "scene_version",
          "instance_id",
          "source_sku",
        ])
        || !isPositiveInteger(value.plan_version_id)
        || !isPositiveInteger(value.scene_id)
        || !isPositiveInteger(value.scene_version)
        || !isIdentifier(value.instance_id, 100)
        || !isIdentifier(value.source_sku, 50)
      ) return null;
      break;
    default:
      return null;
  }

  return value as unknown as DesignFeedbackEventRequest;
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function removePartition(storage: Storage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // 浏览器禁用存储时保持内存与网络侧 fail closed。
  }
}

export function feedbackOutboxStorageKey(taskId: number): string | null {
  return isPositiveInteger(taskId) ? `${STORAGE_PREFIX}:${taskId}` : null;
}

export function readFeedbackOutbox(
  storage: Storage | null,
  taskId: number,
): FeedbackOutboxEntry[] {
  const key = feedbackOutboxStorageKey(taskId);
  if (!storage || !key) return [];

  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    return [];
  }
  if (raw === null) return [];
  if (byteLength(raw) > FEEDBACK_OUTBOX_MAX_BYTES) {
    removePartition(storage, key);
    return [];
  }

  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      !isRecord(parsed)
      || !hasExactKeys(parsed, ["version", "task_id", "entries"])
      || parsed.version !== 1
      || parsed.task_id !== taskId
      || !Array.isArray(parsed.entries)
      || parsed.entries.length > FEEDBACK_OUTBOX_MAX_EVENTS
    ) {
      throw new Error("invalid feedback outbox envelope");
    }

    const clientEventIds = new Set<string>();
    const entries = parsed.entries.map((candidate): FeedbackOutboxEntry => {
      if (!isRecord(candidate) || !hasExactKeys(candidate, ["request", "label"])) {
        throw new Error("invalid feedback outbox entry");
      }
      const request = parseFeedbackRequest(candidate.request);
      if (
        !request
        || candidate.label !== ACTION_LABELS[request.action_type]
        || clientEventIds.has(request.client_event_id)
      ) {
        throw new Error("invalid feedback outbox request");
      }
      clientEventIds.add(request.client_event_id);
      return { request, label: candidate.label };
    });
    return entries;
  } catch {
    removePartition(storage, key);
    return [];
  }
}

function writeFeedbackOutbox(
  storage: Storage,
  taskId: number,
  entries: FeedbackOutboxEntry[],
): boolean {
  const key = feedbackOutboxStorageKey(taskId);
  if (!key || entries.length > FEEDBACK_OUTBOX_MAX_EVENTS) return false;
  if (entries.length === 0) {
    removePartition(storage, key);
    return true;
  }
  const envelope: FeedbackOutboxEnvelope = { version: 1, task_id: taskId, entries };
  const raw = JSON.stringify(envelope);
  if (byteLength(raw) > FEEDBACK_OUTBOX_MAX_BYTES) return false;
  try {
    storage.setItem(key, raw);
    return true;
  } catch {
    return false;
  }
}

function enqueueFeedback(
  storage: Storage,
  taskId: number,
  requestValue: DesignFeedbackEventRequest,
): FeedbackOutboxEntry | null {
  const request = parseFeedbackRequest(requestValue);
  if (!request) return null;
  const entries = readFeedbackOutbox(storage, taskId);
  const existing = entries.find(
    (entry) => entry.request.client_event_id === request.client_event_id,
  );
  if (existing) {
    return JSON.stringify(existing.request) === JSON.stringify(request) ? existing : null;
  }
  if (entries.length >= FEEDBACK_OUTBOX_MAX_EVENTS) return null;

  const entry = { request, label: ACTION_LABELS[request.action_type] };
  return writeFeedbackOutbox(storage, taskId, [...entries, entry]) ? entry : null;
}

function acknowledgeFeedback(storage: Storage, taskId: number, clientEventId: string): void {
  const entries = readFeedbackOutbox(storage, taskId);
  const pending = entries.filter(
    (entry) => entry.request.client_event_id !== clientEventId,
  );
  if (pending.length !== entries.length) writeFeedbackOutbox(storage, taskId, pending);
}

export function createFeedbackOutbox(options: FeedbackOutboxOptions) {
  const { taskId, storage, send, onlineTarget = null, onDeliveryAction } = options;
  let started = false;

  const deliver = async (entry: FeedbackOutboxEntry, retrying: boolean) => {
    const clientEventId = entry.request.client_event_id;
    const inFlightKey = `${taskId}:${clientEventId}`;
    if (
      !storage
      || !feedbackOutboxStorageKey(taskId)
      || PAGE_IN_FLIGHT_EVENTS.has(inFlightKey)
    ) return;
    PAGE_IN_FLIGHT_EVENTS.add(inFlightKey);
    if (retrying) onDeliveryAction?.({ type: "retrying", clientEventId });
    try {
      await send(taskId, entry.request);
      acknowledgeFeedback(storage, taskId, clientEventId);
      onDeliveryAction?.({
        type: "sent",
        clientEventId,
        message: `${entry.label}已同步`,
      });
    } catch {
      onDeliveryAction?.({
        type: "failed",
        clientEventId,
        message: entry.request.action_type === "final_select"
          ? "方案确认暂未同步，可重试"
          : `${entry.label}反馈暂未同步，本地操作已保留，可重试`,
      });
    } finally {
      PAGE_IN_FLIGHT_EVENTS.delete(inFlightKey);
    }
  };

  const flush = () => {
    if (!storage || !feedbackOutboxStorageKey(taskId)) return;
    for (const entry of readFeedbackOutbox(storage, taskId)) {
      void deliver(entry, true);
    }
  };

  const handleOnline: EventListener = () => flush();

  const reportPersistenceFailure = (request: DesignFeedbackEventRequest) => {
    const parsedRequest = parseFeedbackRequest(request);
    if (!parsedRequest) return;
    const label = ACTION_LABELS[parsedRequest.action_type];
    onDeliveryAction?.({ type: "queued", request: parsedRequest, label });
    onDeliveryAction?.({
      type: "failed",
      clientEventId: parsedRequest.client_event_id,
      message: "浏览器无法保存待同步反馈，请检查隐私或存储设置后重试",
    });
  };

  return {
    start() {
      if (started || !storage || !feedbackOutboxStorageKey(taskId)) return;
      started = true;
      onlineTarget?.addEventListener("online", handleOnline);
      const entries = readFeedbackOutbox(storage, taskId);
      for (const entry of entries) {
        onDeliveryAction?.({ type: "queued", request: entry.request, label: entry.label });
        void deliver(entry, false);
      }
    },
    stop() {
      if (!started) return;
      started = false;
      onlineTarget?.removeEventListener("online", handleOnline);
    },
    submit(request: DesignFeedbackEventRequest, _label: string) {
      if (!feedbackOutboxStorageKey(taskId)) return;
      if (!storage) {
        reportPersistenceFailure(request);
        return;
      }
      const entry = enqueueFeedback(storage, taskId, request);
      if (!entry) {
        reportPersistenceFailure(request);
        return;
      }
      onDeliveryAction?.({ type: "queued", request: entry.request, label: entry.label });
      void deliver(entry, false);
    },
    retry(request: DesignFeedbackEventRequest) {
      if (!feedbackOutboxStorageKey(taskId)) return;
      if (!storage) {
        reportPersistenceFailure(request);
        return;
      }
      const entry = enqueueFeedback(storage, taskId, request);
      if (entry) void deliver(entry, true);
      else reportPersistenceFailure(request);
    },
    flush,
  };
}
