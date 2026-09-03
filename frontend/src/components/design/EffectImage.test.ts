import { describe, expect, it } from "vitest";

import {
  effectRenderFailureMessage,
  visibleEffectRenderStatus,
} from "./EffectImage";
import type { EffectRenderJob } from "@/api/designApi";


function job(status: EffectRenderJob["status"], imageUrl: string | null = null): EffectRenderJob {
  return {
    jobId: 1,
    taskId: 1,
    planVersionId: 1,
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

  it("明确展示供应商不可用、死信和取消", () => {
    expect(effectRenderFailureMessage(job("provider_unavailable"))).toContain("暂不可用");
    expect(effectRenderFailureMessage(job("dead_letter"))).toContain("重试已耗尽");
    expect(effectRenderFailureMessage(job("cancelled"))).toContain("已取消");
  });
});
