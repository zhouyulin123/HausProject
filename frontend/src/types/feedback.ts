interface FeedbackEventBase {
  client_event_id: string;
  room_id?: string;
}

export interface AdoptFeedbackEvent extends FeedbackEventBase {
  action_type: "adopt";
  plan_version_id: number;
  target_sku: string;
}

export interface RemoveFeedbackEvent extends FeedbackEventBase {
  action_type: "remove";
  plan_version_id: number;
  source_sku: string;
}

export interface ReplaceFeedbackEvent extends FeedbackEventBase {
  action_type: "replace";
  plan_version_id: number;
  source_sku: string;
  target_sku: string;
}

export interface MoveFeedbackEvent extends FeedbackEventBase {
  action_type: "move";
  scene_id: number;
  scene_version: number;
  instance_id: string;
}

export interface FinalSelectFeedbackEvent extends FeedbackEventBase {
  action_type: "final_select";
  plan_version_id: number;
  satisfaction_score?: 1 | 2 | 3 | 4 | 5;
}

export interface GlbLoadFailureFeedbackEvent extends FeedbackEventBase {
  action_type: "glb_load_failed";
  plan_version_id: number;
  scene_id: number;
  scene_version: number;
  instance_id: string;
  source_sku: string;
}

export type DesignFeedbackEventRequest =
  | AdoptFeedbackEvent
  | RemoveFeedbackEvent
  | ReplaceFeedbackEvent
  | MoveFeedbackEvent
  | FinalSelectFeedbackEvent
  | GlbLoadFailureFeedbackEvent;

export type FeedbackAction = DesignFeedbackEventRequest["action_type"];

export interface DesignFeedbackEventResponse {
  id: number;
  task_id: number;
  client_event_id: string;
  action_type: FeedbackAction;
  plan_version_id: number | null;
  scene_id: number | null;
  scene_version: number | null;
  room_id: string | null;
  instance_id: string | null;
  source_sku: string | null;
  target_sku: string | null;
  satisfaction_score: number | null;
  created_at: string;
}

export type FeedbackDeliveryStatus = "sending" | "sent" | "failed";

export interface FeedbackDelivery {
  request: DesignFeedbackEventRequest;
  label: string;
  status: FeedbackDeliveryStatus;
  message: string;
}
