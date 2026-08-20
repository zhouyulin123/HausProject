import type { UserRequirement } from "@/types/requirement";

/**
 * 根据用户在 Customize 表单里填的内容，拼一段真实的开场白。
 * 不再是写死的"我已了解你的基础需求"——
 * 而是引用具体空间、风格、预算、家庭情况，再问一个针对性的问题。
 */
export function buildOpeningMessage(requirement: UserRequirement): string {
  const parts: string[] = [];

  const area = requirement.area ? `${requirement.area} 平` : "";
  const houseType = requirement.houseType || "";
  const rooms = requirement.rooms.join("、");
  const spaceDesc = [houseType, area, rooms ? `主空间是 ${rooms}` : ""]
    .filter(Boolean)
    .join(" ");
  if (spaceDesc.trim()) {
    parts.push(`你目前是 ${spaceDesc.trim()}`);
  }

  if (requirement.styles.length) {
    parts.push(`偏 ${requirement.styles.join("、")} 风格`);
  }
  if (requirement.budgetRange) {
    parts.push(`预算 ${requirement.budgetRange}`);
  }

  const lifeParts: string[] = [];
  if (requirement.familySize > 2) lifeParts.push(`${requirement.familySize} 口之家`);
  if (requirement.hasChildren) lifeParts.push("有孩子");
  if (requirement.hasPets) lifeParts.push("养宠物");
  if (requirement.hasElderly) lifeParts.push("有老人同住");
  if (requirement.workFromHome) lifeParts.push("在家办公");
  if (requirement.needStorage) lifeParts.push("重收纳");
  if (requirement.smartHome) lifeParts.push("希望接入智能家居");
  if (lifeParts.length) parts.push(lifeParts.join("、"));

  if (parts.length > 0) {
    const summary = parts.join("，") + "。";
    return `${summary}这些我都记下了。${pickOpeningQuestion(requirement)}`;
  }

  return "嗨，我还没看到你的需求细节。你可以在下方直接告诉我：想装修哪个空间、偏爱的风格、预算大概多少，或者把房间照片发上来，我来帮你拆解。";
}

function pickOpeningQuestion(req: UserRequirement): string {
  if (req.rooms.length === 0) {
    return "先告诉我你最想装修哪个空间？客厅、卧室、还是全屋？";
  }
  if (req.styles.length === 0) {
    return "有没有偏爱的风格？比如奶油、原木、现代简约、轻法式…";
  }
  if (!req.budgetRange) {
    return "你的预算大概多少？我好帮你平衡风格和品质。";
  }
  if (req.hasPets) {
    return "养宠物的话，沙发布料和地面材质我会特别注意耐磨易清洁。还有哪些特别的居住习惯要告诉我？";
  }
  if (req.hasChildren) {
    return "有孩子的话，家具圆角和环保板材我会优先考虑。还有什么生活习惯需要我注意的？";
  }
  if (req.needStorage) {
    return "你提到重收纳，那玄关、卧室、阳台这些地方我会重点设计储物。还有什么想补充的？";
  }
  return "在生成方案前，还有什么想补充的吗？比如采光、色彩偏好，或者材质上的禁忌。";
}