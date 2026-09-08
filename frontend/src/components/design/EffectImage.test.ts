import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";

import EffectImage, {
  effectRenderAvailability,
  effectRenderFailureMessage,
  effectRenderMatchesScene,
  visibleEffectRenderStatus,
} from "./EffectImage";
import type { EffectRenderJob } from "@/api/designApi";
import { mockDesigns } from "@/data/mockDesigns";


function job(status: EffectRenderJob["status"], imageUrl: string | null = null): EffectRenderJob {
  return {
    jobId: 1,
    taskId: 1,
    planVersionId: 1,
    sceneId: 9,
    sceneVersion: 3,
    status,
    progress: status === "completed" ? 100 : 10,
    attemptCount: 1,
    maxAttempts: 2,
    imageUrl,
    mode: imageUrl ? "text2img" : null,
    errorMessage: null,
  };
}


describe("效果图任务展示状态", () => {
  it("排队与执行中保持轮询，完成后展示服务端图片", () => {
    expect(visibleEffectRenderStatus(job("queued"))).toBe("loading");
    expect(visibleEffectRenderStatus(job("running"))).toBe("loading");
    expect(visibleEffectRenderStatus(job("completed", "/uploads/a.png"))).toBe("done");
  });

  it("仅允许当前服务端已保存场景版本生成效果图", () => {
    expect(effectRenderAvailability({
      syncState: "saved",
      sceneId: 9,
      sceneVersion: 3,
    })).toEqual({ ready: true, message: "场景版本 3 已保存" });
    expect(effectRenderAvailability({
      syncState: "dirty",
      sceneId: 9,
      sceneVersion: 3,
    })).toMatchObject({ ready: false, message: expect.stringContaining("尚未保存") });
    expect(effectRenderAvailability({
      syncState: "saving",
      sceneId: 9,
      sceneVersion: 3,
    })).toMatchObject({ ready: false });
    expect(effectRenderAvailability({
      syncState: "demo",
      sceneId: null,
      sceneVersion: null,
    })).toMatchObject({ ready: false, message: expect.stringContaining("服务端场景") });
  });

  it("不展示其他场景或其他版本的恢复任务", () => {
    const current = job("completed", "/uploads/a.png");
    expect(effectRenderMatchesScene(current, { sceneId: 9, sceneVersion: 3 })).toBe(true);
    expect(effectRenderMatchesScene(current, { sceneId: 9, sceneVersion: 4 })).toBe(false);
    expect(effectRenderMatchesScene(current, { sceneId: 10, sceneVersion: 3 })).toBe(false);
  });

  it("场景有未保存编辑时禁用按钮并解释原因", () => {
    const html = renderToStaticMarkup(
      createElement(EffectImage, {
        plan: { ...mockDesigns[0], planVersionId: 42 },
        sceneBinding: { syncState: "dirty", sceneId: 9, sceneVersion: 3 },
      }),
    );

    expect(html).toContain("当前 3D 编辑尚未保存");
    expect(html).toContain("disabled");
  });

  it("明确展示供应商不可用、死信和取消", () => {
    expect(effectRenderFailureMessage(job("provider_unavailable"))).toContain("暂不可用");
    expect(effectRenderFailureMessage(job("dead_letter"))).toContain("重试已耗尽");
    expect(effectRenderFailureMessage(job("cancelled"))).toContain("已取消");
  });
});
