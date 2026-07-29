export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const SESSION_ID_KEY = "haus-anonymous-session-id";
const TASK_ID_KEY = "haus-current-task-id";
const IMAGE_IDS_KEY = "haus-uploaded-image-ids";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function readSessionId(storage: KeyValueStorage): string | null {
  const value = storage.getItem(SESSION_ID_KEY);
  return value && UUID_PATTERN.test(value) ? value : null;
}

export function writeSessionId(
  storage: KeyValueStorage,
  sessionId: string | null,
): void {
  if (sessionId) storage.setItem(SESSION_ID_KEY, sessionId);
  else storage.removeItem(SESSION_ID_KEY);
}

export function readTaskId(storage: KeyValueStorage): number | null {
  const value = Number(storage.getItem(TASK_ID_KEY));
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function writeTaskId(
  storage: KeyValueStorage,
  taskId: number | null,
): void {
  if (taskId && Number.isInteger(taskId) && taskId > 0) {
    storage.setItem(TASK_ID_KEY, String(taskId));
  } else {
    storage.removeItem(TASK_ID_KEY);
  }
}

export function readImageIds(storage: KeyValueStorage): number[] {
  try {
    const value = JSON.parse(storage.getItem(IMAGE_IDS_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    return [...new Set(value.filter((id) => Number.isInteger(id) && id > 0))];
  } catch {
    return [];
  }
}

export function writeImageIds(
  storage: KeyValueStorage,
  imageIds: number[],
): void {
  const validIds = [
    ...new Set(imageIds.filter((id) => Number.isInteger(id) && id > 0)),
  ];
  storage.setItem(IMAGE_IDS_KEY, JSON.stringify(validIds));
}
