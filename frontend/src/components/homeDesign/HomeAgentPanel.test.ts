import { describe, it, expect } from "vitest";
import {
  budgetStatusLabel,
  parsePendingAgentRequest,
  proposalBlock,
  proposalDiff,
} from "./HomeAgentPanel";
import type { HomeDesignDocument, HomeAgentResponse } from "@/types/homeDesign";
const document: HomeDesignDocument = {
  schema_version: "home-design/1.0",
  space_version: 2,
  surfaces: [],
  objects: [],
};
const proposal: HomeAgentResponse = {
  turn_id: 1,
  outcome: "proposal",
  message: "建议",
  candidate_document: document,
  validation: { valid: true, issues: [] },
  base_version: 3,
  space_version: 2,
  evidence: {
    schema_version: "home-agent-evidence/1.0",
    asset_refs: [],
    rule_version: "catalog-eligibility/home-agent-budget/1.0",
  },
  budget_preview: {
    currency: "CNY",
    known_subtotal: 1200,
    pending_count: 0,
    total_price: 1200,
    budget_max: 20000,
    region: "CN-SH",
    budget_status: "within",
    limitations: [],
  },
};
describe("AI候选应用门禁", () => {
  it("干净、精确版本、有效候选方可应用", () =>
    expect(proposalBlock(proposal, 3, document, false, true)).toBe(""));
  it.each(["invalid", "clarify", "unsupported"] as const)(
    "%s不可应用",
    (outcome) =>
      expect(
        proposalBlock({ ...proposal, outcome }, 3, document, false, true),
      ).not.toBe(""),
  );
  it("草稿与失配版本均阻断", () => {
    expect(proposalBlock(proposal, 3, document, true, true)).not.toBe("");
    expect(proposalBlock(proposal, 4, document, false, true)).not.toBe("");
    expect(
      proposalBlock(
        { ...proposal, space_version: 1 },
        3,
        document,
        false,
        true,
      ),
    ).not.toBe("");
    expect(
      proposalBlock(
        { ...proposal, validation: { valid: false, issues: [] } },
        3,
        document,
        false,
        true,
      ),
    ).not.toBe("");
  });
  it("超出预算时不可应用", () =>
    expect(
      proposalBlock(
        {
          ...proposal,
          budget_preview: {
            ...proposal.budget_preview,
            budget_status: "over",
          },
        },
        3,
        document,
        false,
        true,
      ),
    ).not.toBe(""));
  it("未知和不完整预算不得显示为预算内", () => {
    expect(budgetStatusLabel("unknown")).not.toContain("预算内");
    expect(budgetStatusLabel("incomplete")).not.toContain("预算内");
    expect(budgetStatusLabel("within")).toContain("预算内");
  });
  it("刷新后只恢复完整的原轮配置", () => {
    const original = {
      client_turn_id: "turn-1",
      base_version: 3,
      space_version: 2,
      message: "用授权椅子布置阅读角",
      region: "CN-SH",
      budget_max: 20000,
      allowed_asset_ids: [9, 12],
    };
    expect(parsePendingAgentRequest(JSON.stringify(original))).toEqual(original);
    expect(
      parsePendingAgentRequest(
        JSON.stringify({ ...original, allowed_asset_ids: [9, 9] }),
      ),
    ).toBeNull();
    expect(
      parsePendingAgentRequest(JSON.stringify({ ...original, region: "上海" })),
    ).toBeNull();
    expect(parsePendingAgentRequest("broken")).toBeNull();
  });
  it("只预览变化不写原文档", () => {
    const candidate = {
      ...document,
      surfaces: [
        {
          id: "x",
          kind: "floor" as const,
          wall_id: null,
          room_id: "r",
          material: { name: "橡木", color: "#ffffff" },
        },
      ],
    };
    expect(proposalDiff(document, candidate)).toEqual(["新增饰面：橡木"]);
    expect(document.surfaces).toHaveLength(0);
  });
});
