import { useState } from "react";
import { AlertTriangle, Check, X } from "lucide-react";
import type { AgentApproval } from "@/api/designApi";

const approvalLabels: Record<AgentApproval["approval_type"], string> = {
  quote_review: "报价复核",
  construction_risk: "施工风险",
  quality_gate: "质量复核",
};

const statusLabels: Record<AgentApproval["status"], string> = {
  pending: "待处理",
  approved: "已确认",
  rejected: "已驳回",
};

interface AgentApprovalPanelProps {
  approvals: AgentApproval[];
  loading: boolean;
  error: string;
  decidingId: number | null;
  onDecision: (
    approval: AgentApproval,
    decision: "approve" | "reject",
    conclusion: string,
  ) => void;
}

export default function AgentApprovalPanel({
  approvals,
  loading,
  error,
  decidingId,
  onDecision,
}: AgentApprovalPanelProps) {
  const [conclusions, setConclusions] = useState<Record<number, string>>({});

  if (!loading && !error && approvals.length === 0) return null;

  return (
    <section aria-label="人工审批" className="mb-3 border border-[#8f7040] bg-[#2b2718] px-4 py-3 text-[#f0d39e]">
      <div className="flex items-center gap-2 text-xs font-semibold">
        <AlertTriangle className="h-4 w-4" /> 人工审批
      </div>
      {loading && <p className="mt-2 text-xs text-[#c8b58d]">正在读取审批记录…</p>}
      {error && <p role="alert" className="mt-2 text-xs text-[#ffb4a8]">{error}</p>}
      <div className="mt-2 space-y-3">
        {approvals.map((approval) => {
          const conclusion = conclusions[approval.id] ?? "";
          const pending = approval.status === "pending";
          const deciding = decidingId === approval.id;
          return (
            <article key={approval.id} className="border-t border-[#8f7040]/45 pt-3 first:border-t-0 first:pt-0">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium">{approvalLabels[approval.approval_type]}</p>
                <span className="font-mono text-[10px]">{statusLabels[approval.status]}</span>
              </div>
              <p className="mt-1 text-xs leading-5 text-[#e0c998]">{approval.request_reason}</p>
              {approval.approval_type === "construction_risk" && pending && (
                <p className="mt-1 text-[10px] leading-4 text-[#ffcf9f]">
                  施工风险只能由管理员受控复核；平台结论不代表施工资质或施工许可。
                </p>
              )}
              {pending ? (
                <>
                  <textarea
                    rows={2}
                    value={conclusion}
                    placeholder="填写审核结论"
                    onChange={(event) => setConclusions((current) => ({
                      ...current,
                      [approval.id]: event.target.value,
                    }))}
                    className="mt-2 w-full resize-none border border-[#8f7040]/60 bg-[#171e18] px-3 py-2 text-xs text-[#f0d39e] outline-none placeholder:text-[#907f61] focus:border-[#d5ff67]"
                  />
                  <div className="mt-2 flex justify-end gap-2">
                    {approval.approval_type !== "construction_risk" && (
                      <button
                        type="button"
                        disabled={!conclusion.trim() || deciding}
                        onClick={() => onDecision(approval, "approve", conclusion.trim())}
                        className="inline-flex min-h-9 items-center gap-1.5 border border-[#6e8049] px-3 text-xs disabled:opacity-40"
                      >
                        <Check className="h-3.5 w-3.5" /> 确认
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={!conclusion.trim() || deciding}
                      onClick={() => onDecision(approval, "reject", conclusion.trim())}
                      className="inline-flex min-h-9 items-center gap-1.5 border border-[#a55d52] px-3 text-xs disabled:opacity-40"
                    >
                      <X className="h-3.5 w-3.5" /> 驳回
                    </button>
                  </div>
                </>
              ) : (
                approval.conclusion && <p className="mt-2 text-xs leading-5">{approval.conclusion}</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
