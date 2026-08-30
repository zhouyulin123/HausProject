type RetryOptions = {
  delaysMs?: readonly number[];
  wait?: (delayMs: number) => Promise<void>;
};

const DEFAULT_RETRY_DELAYS_MS = [250, 750, 1500] as const;
const TRANSIENT_IMPORT_MESSAGES = [
  /failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /importing a module script failed/i,
  /loading chunk .+ failed/i,
  /chunkloaderror/i,
  /networkerror when attempting to fetch resource/i,
  /fetch failed/i,
];

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return typeof error === "string" ? error : "";
}

export function isTransientLazyImportError(error: unknown): boolean {
  const message = errorMessage(error);
  return TRANSIENT_IMPORT_MESSAGES.some((pattern) => pattern.test(message));
}

const sleep = (delayMs: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, delayMs));

export async function importWithRetry<T>(
  importer: () => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const delaysMs = options.delaysMs ?? DEFAULT_RETRY_DELAYS_MS;
  const wait = options.wait ?? sleep;

  for (let attempt = 0; ; attempt += 1) {
    try {
      return await importer();
    } catch (error) {
      if (!isTransientLazyImportError(error) || attempt >= delaysMs.length) {
        throw error;
      }
      await wait(delaysMs[attempt]);
    }
  }
}
