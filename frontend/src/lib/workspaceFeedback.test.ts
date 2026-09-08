import { describe, expect, it } from "vitest";
import {
  buildGlbLoadFailureFeedbackEvent,
  buildFinalSelectFeedbackEvent,
  buildFurnitureFeedbackEvent,
  buildMoveFeedbackEvent,
  buildReplaceFeedbackEvent,
  createMoveFeedbackReporter,
  createFeedbackClientEventId,
  feedbackDeliveryReducer,
} from "./workspaceFeedback";

describe("工作台结构化反馈事件", () => {
  it("用资源事实生成确定性且最小的 GLB 加载失败事件", () => {
    const input = {
      taskId: 42,
      planVersionId: 8,
      sceneId: 3,
      sceneVersion: 7,
      instanceId: "sofa-main",
      sku: "sofa-old",
    };

    const first = buildGlbLoadFailureFeedbackEvent(input);
    const second = buildGlbLoadFailureFeedbackEvent(input);

    expect(first).toEqual(second);
    expect(first).toEqual({
      client_event_id: expect.stringMatching(
        /^feedback-42-glb_load_failed-[a-f0-9]{8}$/,
      ),
      action_type: "glb_load_failed",
      plan_version_id: 8,
      scene_id: 3,
      scene_version: 7,
      instance_id: "sofa-main",
      source_sku: "SOFA-OLD",
    });
    expect(JSON.stringify(first)).not.toMatch(/url|message|stack/i);
  });

  it("缺少任一持久化资源事实时不构造 GLB 失败事件", () => {
    expect(
      buildGlbLoadFailureFeedbackEvent({
        taskId: 42,
        planVersionId: 8,
        sceneId: null,
        sceneVersion: 7,
        instanceId: "sofa-main",
        sku: "SOFA-OLD",
      }),
    ).toBeNull();
  });

  it("只有服务端方案版本与 SKU 同时存在时才构建采用或移除事件", () => {
    expect(buildFurnitureFeedbackEvent({
      clientEventId: "feedback-42-adopt-001",
      selectedBeforeToggle: false,
      planVersionId: 8,
      sku: "SOFA-001",
      roomId: "living-room",
    })).toEqual({
      client_event_id: "feedback-42-adopt-001",
      action_type: "adopt",
      plan_version_id: 8,
      target_sku: "SOFA-001",
      room_id: "living-room",
    });
    expect(buildFurnitureFeedbackEvent({
      clientEventId: "feedback-42-remove-001",
      selectedBeforeToggle: true,
      planVersionId: 8,
      sku: "SOFA-001",
      roomId: null,
    })).toEqual({
      client_event_id: "feedback-42-remove-001",
      action_type: "remove",
      plan_version_id: 8,
      source_sku: "SOFA-001",
    });
    expect(buildFurnitureFeedbackEvent({
      clientEventId: "feedback-42-adopt-002",
      selectedBeforeToggle: false,
      planVersionId: null,
      sku: "SOFA-001",
      roomId: null,
    })).toBeNull();
    expect(buildFurnitureFeedbackEvent({
      clientEventId: "feedback-42-adopt-003",
      selectedBeforeToggle: false,
      planVersionId: 8,
      sku: undefined,
      roomId: null,
    })).toBeNull();
  });

  it("最终确认仅接受服务端方案版本和可选 1-5 满意度", () => {
    expect(buildFinalSelectFeedbackEvent("feedback-42-final-001", 8, 5)).toEqual({
      client_event_id: "feedback-42-final-001",
      action_type: "final_select",
      plan_version_id: 8,
      satisfaction_score: 5,
    });
    expect(buildFinalSelectFeedbackEvent("feedback-42-final-002", 8, null)).toEqual({
      client_event_id: "feedback-42-final-002",
      action_type: "final_select",
      plan_version_id: 8,
    });
    expect(buildFinalSelectFeedbackEvent("feedback-42-final-003", null, 3)).toBeNull();
    expect(buildFinalSelectFeedbackEvent("feedback-42-final-004", 8, 6)).toBeNull();
  });

  it("移动事件缺少真实场景、版本或实例任一字段时保持静默", () => {
    expect(buildMoveFeedbackEvent("feedback-42-move-001", 3, 7, "sofa-1", "living-room")).toEqual({
      client_event_id: "feedback-42-move-001",
      action_type: "move",
      scene_id: 3,
      scene_version: 7,
      instance_id: "sofa-1",
      room_id: "living-room",
    });
    expect(buildMoveFeedbackEvent("feedback-42-move-002", null, 7, "sofa-1", null)).toBeNull();
    expect(buildMoveFeedbackEvent("feedback-42-move-003", 3, null, "sofa-1", null)).toBeNull();
    expect(buildMoveFeedbackEvent("feedback-42-move-004", 3, 7, null, null)).toBeNull();
  });

  it("移动持久化成功后按场景版本与实例只投递一次", () => {
    const submitted: unknown[] = [];
    const reportMove = createMoveFeedbackReporter({
      taskId: 42,
      planVersionId: 8,
      roomId: "living-room",
      submit: (request, label) => submitted.push({ request, label }),
    });

    reportMove({ sceneId: 3, sceneVersion: 7, instanceId: "sofa-1" });
    reportMove({ sceneId: 3, sceneVersion: 7, instanceId: "sofa-1" });
    reportMove({ sceneId: 3, sceneVersion: 8, instanceId: "sofa-1" });

    expect(submitted).toHaveLength(2);
    expect(submitted[0]).toEqual({
      request: expect.objectContaining({
        action_type: "move",
        scene_id: 3,
        scene_version: 7,
        instance_id: "sofa-1",
      }),
      label: "家具位置调整",
    });
  });

  it("移动上下文缺少任务、方案或持久化场景事实时不投递", () => {
    const submitted: unknown[] = [];
    const reportMove = createMoveFeedbackReporter({
      taskId: 42,
      planVersionId: null,
      roomId: null,
      submit: (request) => submitted.push(request),
    });

    reportMove({ sceneId: 3, sceneVersion: 7, instanceId: "sofa-1" });
    reportMove({ sceneId: 3, sceneVersion: 0, instanceId: "sofa-1" });
    reportMove({ sceneId: 3, sceneVersion: 7, instanceId: "" });

    expect(submitted).toEqual([]);
  });

  it("替换事件只接受真实方案版本和两个不同的 SKU", () => {
    expect(buildReplaceFeedbackEvent({
      clientEventId: "feedback-42-replace-001",
      planVersionId: 8,
      sourceSku: "SOFA-OLD",
      targetSku: "SOFA-NEW",
      roomId: "living-room",
    })).toEqual({
      client_event_id: "feedback-42-replace-001",
      action_type: "replace",
      plan_version_id: 8,
      source_sku: "SOFA-OLD",
      target_sku: "SOFA-NEW",
      room_id: "living-room",
    });
    expect(buildReplaceFeedbackEvent({
      clientEventId: "feedback-42-replace-002",
      planVersionId: null,
      sourceSku: "SOFA-OLD",
      targetSku: "SOFA-NEW",
      roomId: null,
    })).toBeNull();
    expect(buildReplaceFeedbackEvent({
      clientEventId: "feedback-42-replace-003",
      planVersionId: 8,
      sourceSku: "SOFA-OLD",
      targetSku: " sofa-old ",
      roomId: null,
    })).toBeNull();
  });

  it("重试保留首次请求的稳定幂等键", () => {
    const clientEventId = createFeedbackClientEventId(42, "adopt", "fixed-nonce");
    const request = buildFurnitureFeedbackEvent({
      clientEventId,
      selectedBeforeToggle: false,
      planVersionId: 8,
      sku: "SOFA-001",
      roomId: null,
    })!;
    const queued = feedbackDeliveryReducer([], {
      type: "queued",
      request,
      label: "已加入云朵沙发",
    });
    const failed = feedbackDeliveryReducer(queued, {
      type: "failed",
      clientEventId,
      message: "反馈暂未同步，可重试",
    });
    const retrying = feedbackDeliveryReducer(failed, {
      type: "retrying",
      clientEventId,
    });

    expect(clientEventId).toBe("feedback-42-adopt-fixed-nonce");
    expect(retrying[0]?.request.client_event_id).toBe(clientEventId);
    expect(retrying[0]?.status).toBe("sending");
  });
});
