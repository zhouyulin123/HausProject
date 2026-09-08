interface TimelinePollingOptions {
  poll: () => Promise<void>;
  isHidden: () => boolean;
  schedule?: (callback: () => void, delayMs: number) => number;
  clear?: (timer: number) => void;
  baseDelayMs?: number;
  maxDelayMs?: number;
}

export interface TaskTimelinePollingLoop {
  start: () => void;
  stop: () => void;
  visibilityChanged: () => void;
}

export function createTaskTimelinePollingLoop({
  poll,
  isHidden,
  schedule = (callback, delayMs) => window.setTimeout(callback, delayMs),
  clear = (timer) => window.clearTimeout(timer),
  baseDelayMs = 5_000,
  maxDelayMs = 60_000,
}: TimelinePollingOptions): TaskTimelinePollingLoop {
  let stopped = true;
  let inFlight = false;
  let failureCount = 0;
  let timer: number | null = null;

  const clearScheduled = () => {
    if (timer !== null) clear(timer);
    timer = null;
  };

  const scheduleNext = () => {
    if (stopped || isHidden()) return;
    const delay = Math.min(baseDelayMs * (2 ** failureCount), maxDelayMs);
    clearScheduled();
    timer = schedule(() => { void run(); }, delay);
  };

  const run = async () => {
    if (stopped || isHidden() || inFlight) return;
    inFlight = true;
    try {
      await poll();
      failureCount = 0;
    } catch {
      failureCount += 1;
    } finally {
      inFlight = false;
      scheduleNext();
    }
  };

  return {
    start() {
      if (!stopped) return;
      stopped = false;
      void run();
    },
    stop() {
      stopped = true;
      clearScheduled();
    },
    visibilityChanged() {
      clearScheduled();
      if (!stopped && !isHidden()) void run();
    },
  };
}
