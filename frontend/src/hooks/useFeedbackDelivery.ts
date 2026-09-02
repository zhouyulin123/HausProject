import { useCallback, useEffect, useReducer, useRef } from "react";
import { sendDesignFeedbackEvent } from "@/api/designApi";
import { createFeedbackOutbox } from "@/lib/feedbackOutbox";
import { feedbackDeliveryReducer } from "@/lib/workspaceFeedback";
import type { DesignFeedbackEventRequest, FeedbackDelivery } from "@/types/feedback";

export function useFeedbackDelivery(taskId: number) {
  const [deliveries, dispatch] = useReducer(feedbackDeliveryReducer, []);
  const outboxRef = useRef<ReturnType<typeof createFeedbackOutbox> | null>(null);

  useEffect(() => {
    dispatch({ type: "reset" });
    let storage: Storage | null = null;
    try {
      storage = typeof window === "undefined" ? null : window.localStorage;
    } catch {
      storage = null;
    }
    const outbox = createFeedbackOutbox({
      taskId,
      storage,
      send: sendDesignFeedbackEvent,
      onlineTarget: typeof window === "undefined" ? null : window,
      onDeliveryAction: dispatch,
    });
    outboxRef.current = outbox;
    outbox.start();
    return () => {
      outbox.stop();
      if (outboxRef.current === outbox) outboxRef.current = null;
    };
  }, [taskId]);

  const submit = useCallback((request: DesignFeedbackEventRequest, label: string) => {
    outboxRef.current?.submit(request, label);
  }, []);

  const retry = useCallback((delivery: FeedbackDelivery) => {
    outboxRef.current?.retry(delivery.request);
  }, []);

  return { deliveries, submit, retry };
}
