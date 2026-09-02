import { useCallback, useReducer, useRef } from "react";
import { sendDesignFeedbackEvent } from "@/api/designApi";
import { feedbackDeliveryReducer } from "@/lib/workspaceFeedback";
import type { DesignFeedbackEventRequest, FeedbackDelivery } from "@/types/feedback";

export function useFeedbackDelivery(taskId: number) {
  const [deliveries, dispatch] = useReducer(feedbackDeliveryReducer, []);
  const inFlight = useRef(new Set<string>());

  const deliver = useCallback(async (
    request: DesignFeedbackEventRequest,
    label: string,
    retrying = false,
  ) => {
    const clientEventId = request.client_event_id;
    if (inFlight.current.has(clientEventId)) return;
    inFlight.current.add(clientEventId);
    dispatch(retrying
      ? { type: "retrying", clientEventId }
      : { type: "queued", request, label });
    try {
      await sendDesignFeedbackEvent(taskId, request);
      dispatch({
        type: "sent",
        clientEventId,
        message: `${label}已同步`,
      });
    } catch {
      dispatch({
        type: "failed",
        clientEventId,
        message: request.action_type === "final_select"
          ? "方案确认暂未同步，可重试"
          : `${label}反馈暂未同步，本地操作已保留，可重试`,
      });
    } finally {
      inFlight.current.delete(clientEventId);
    }
  }, [taskId]);

  const submit = useCallback((request: DesignFeedbackEventRequest, label: string) => {
    void deliver(request, label);
  }, [deliver]);

  const retry = useCallback((delivery: FeedbackDelivery) => {
    void deliver(delivery.request, delivery.label, true);
  }, [deliver]);

  return { deliveries, submit, retry };
}
