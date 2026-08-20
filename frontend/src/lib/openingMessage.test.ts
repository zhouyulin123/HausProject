import { describe, it, expect } from "vitest";

import { emptyRequirement } from "@/types/requirement";
import type { UserRequirement } from "@/types/requirement";

import { buildOpeningMessage } from "./openingMessage";

function makeReq(overrides: Partial<UserRequirement> = {}): UserRequirement {
  return { ...emptyRequirement, ...overrides };
}

describe("buildOpeningMessage", () => {
  it("returns a generic guide when nothing is filled in", () => {
    const msg = buildOpeningMessage(emptyRequirement);
    expect(msg).toContain("嗨");
    expect(msg).toContain("需求细节");
  });

  it("references the user's house type, area and rooms", () => {
    const msg = buildOpeningMessage(
      makeReq({
        houseType: "三室两厅",
        area: 110,
        rooms: ["客厅", "主卧"],
        styles: ["奶油风"],
        budgetRange: "15万以内",
      }),
    );
    expect(msg).toContain("三室两厅");
    expect(msg).toContain("110 平");
    expect(msg).toContain("客厅");
    expect(msg).toContain("主卧");
    expect(msg).toContain("奶油风");
    expect(msg).toContain("15万以内");
  });

  it("mentions family and lifestyle signals", () => {
    const msg = buildOpeningMessage(
      makeReq({
        rooms: ["客厅"],
        styles: ["原木风"],
        budgetRange: "10万",
        familySize: 4,
        hasChildren: true,
        hasPets: true,
        needStorage: true,
      }),
    );
    expect(msg).toContain("4 口之家");
    expect(msg).toContain("有孩子");
    expect(msg).toContain("养宠物");
    expect(msg).toContain("重收纳");
  });

  it("picks a pet-focused question when the user has pets", () => {
    const msg = buildOpeningMessage(
      makeReq({
        rooms: ["客厅"],
        styles: ["现代简约"],
        budgetRange: "8万",
        hasPets: true,
      }),
    );
    expect(msg).toContain("耐磨");
  });

  it("asks which room first when room is not yet selected", () => {
    const msg = buildOpeningMessage(
      makeReq({ styles: ["奶油风"], budgetRange: "10万" }),
    );
    expect(msg).toContain("空间");
  });

  it("different inputs produce different opening messages", () => {
    const a = buildOpeningMessage(
      makeReq({ rooms: ["客厅"], styles: ["奶油风"], budgetRange: "10万" }),
    );
    const b = buildOpeningMessage(
      makeReq({ rooms: ["主卧"], styles: ["原木风"], budgetRange: "20万" }),
    );
    expect(a).not.toBe(b);
  });
});