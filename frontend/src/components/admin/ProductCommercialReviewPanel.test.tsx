import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ApiError, type ProductAuditEvent } from "@/api/designApi";
import {
  CommercialReviewControls,
  ProductAuditTimeline,
  commercialReviewErrorMessage,
  createPendingCommercialReview,
  submitCommercialReview,
  type PendingCommercialReview,
} from "./ProductCommercialReviewPanel";

const pending: PendingCommercialReview = {
  productId: 8,
  expectedRecordVersion: 4,
  decision: "approve",
  note: null,
  idempotencyKey: "commercial-review-8-v4-request-1",
};

function auditEvent(overrides: Partial<ProductAuditEvent> = {}): ProductAuditEvent {
  return {
    id: 31,
    product_id: 8,
    event_type: "commercial_review_reject",
    actor: "user:9",
    request_id: "product:request-1",
    changed_fields: ["source_url", "review_note"],
    changes: {
      source_url: {
        before: null,
        after: "https://merchant.example/products/chair?access_token=secret#internal",
      },
      review_note: {
        before: null,
        after: {
          present: true,
          char_count: 6,
          sha256: "abc123",
          raw: "不可展示的拒绝原文",
        },
      },
    },
    decision: "reject",
    resulting_status: "rejected",
    resulting_record_version: 5,
    created_at: "2026-09-10T08:00:00Z",
    ...overrides,
  };
}

describe("商品商业审核交互", () => {
  it("拒绝备注为空时不创建请求，合法请求冻结当前版本与备注", () => {
    const current = {
      id: 8,
      record_version: 4,
    } as Parameters<typeof createPendingCommercialReview>[0];

    expect(() => createPendingCommercialReview(
      current,
      "reject",
      "   ",
      () => "fixed-operation",
    )).toThrow("必须填写原因");
    expect(createPendingCommercialReview(
      current,
      "reject",
      "  来源无法复核  ",
      () => "fixed-operation",
    )).toEqual({
      productId: 8,
      expectedRecordVersion: 4,
      decision: "reject",
      note: "来源无法复核",
      idempotencyKey: "commercial-review-8-v4-reject-fixed-operation",
    });
  });

  it("409 时刷新权威目录且不自动重放", async () => {
    const review = vi.fn().mockRejectedValue(
      new ApiError("conflict", 409, { code: "record_version_conflict" }),
    );
    const refresh = vi.fn().mockResolvedValue(undefined);

    const result = await submitCommercialReview(pending, review, refresh);

    expect(result.outcome).toBe("conflict");
    expect(review).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("网络结果未知后人工重试复用相同版本、内容与幂等键", async () => {
    const review = vi.fn()
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(auditEvent({ decision: "approve" }));
    const refresh = vi.fn().mockResolvedValue(undefined);

    const unknown = await submitCommercialReview(pending, review, refresh);
    const retried = await submitCommercialReview(pending, review, refresh);

    expect(unknown.outcome).toBe("retryable_error");
    expect(retried.outcome).toBe("success");
    expect(review.mock.calls).toEqual([
      [8, { decision: "approve", expectedRecordVersion: 4 }, pending.idempotencyKey],
      [8, { decision: "approve", expectedRecordVersion: 4 }, pending.idempotencyKey],
    ]);
  });

  it("422 显示服务端 reason codes 的中文缺口", () => {
    const error = new ApiError("invalid", 422, {
      code: "commercial_evidence_incomplete",
      reason_codes: ["source_name_missing", "price_observed_at_future"],
    });

    expect(commercialReviewErrorMessage(error)).toContain("缺少来源名称");
    expect(commercialReviewErrorMessage(error)).toContain("价格观察时间晚于检查时间");
  });

  it("422 是已知失败，不刷新也不重放", async () => {
    const review = vi.fn().mockRejectedValue(new ApiError("invalid", 422, {
      code: "commercial_evidence_incomplete",
      reason_codes: ["source_name_missing"],
    }));
    const refresh = vi.fn().mockResolvedValue(undefined);

    const result = await submitCommercialReview(pending, review, refresh);

    expect(result.outcome).toBe("validation_error");
    expect(review).toHaveBeenCalledTimes(1);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("厂家只看到审计入口，不渲染批准或拒绝操作", () => {
    const html = renderToStaticMarkup(
      <CommercialReviewControls
        canReview={false}
        status="draft"
        busy={false}
        onApprove={() => undefined}
        onReject={() => undefined}
      />,
    );

    expect(html).toContain("仅管理员可执行商业审核");
    expect(html).not.toContain(">批准<");
    expect(html).not.toContain(">拒绝<");
  });

  it("审计时间线展示脱敏摘要并移除 URL 查询参数和拒绝原文", () => {
    const html = renderToStaticMarkup(<ProductAuditTimeline events={[auditEvent()]} />);

    expect(html).toContain("商业审核拒绝");
    expect(html).toContain("user:9");
    expect(html).toContain("来源链接");
    expect(html).toContain("https://merchant.example/products/chair");
    expect(html).toContain("字符数 6");
    expect(html).not.toContain("access_token");
    expect(html).not.toContain("不可展示的拒绝原文");
  });
});
