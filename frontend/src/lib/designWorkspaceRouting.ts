export const DESIGN_START_PATH = "/design/new";
export const LEGACY_DESIGN_PATHS = [
  "customize",
  "upload",
  "chat",
  "results",
] as const;

export const WORKSPACE_CATALOG_OPTIONS = {
  fallbackToMock: false,
} as const;

export function parseDesignProjectId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const taskId = Number(value);
  return Number.isSafeInteger(taskId) && taskId > 0 ? taskId : null;
}
