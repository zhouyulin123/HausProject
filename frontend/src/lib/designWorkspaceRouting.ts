export const DESIGN_START_PATH = "/design/new";

export function parseDesignProjectId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const taskId = Number(value);
  return Number.isSafeInteger(taskId) && taskId > 0 ? taskId : null;
}
