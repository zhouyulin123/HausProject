export type HomeExperienceStep = {
  id: "scan" | "understand" | "compose" | "deliver";
  index: string;
  eyebrow: string;
  title: string;
  description: string;
  metric: { value: string; label: string };
  annotations: string[];
};

export const HOME_EXPERIENCE_STEPS: readonly HomeExperienceStep[] = [
  { id: "scan", index: "01", eyebrow: "空间感知", title: "先读懂空间，\n再谈风格。", description: "识别墙体、门窗、采光与可用尺度，把一张房间照片还原成可推演的数字空间。", metric: { value: "需确认", label: "关键空间事实" }, annotations: ["采光方向待识别", "主通道待校验", "结构风险需人工确认"] },
  { id: "understand", index: "02", eyebrow: "生活建模", title: "设计围绕生活，\n而不是效果图。", description: "把预算、家庭成员、宠物、收纳与日常习惯转换成清晰的设计约束。", metric: { value: "结构化", label: "需求与约束" }, annotations: ["家庭成员", "宠物习惯", "收纳需求"] },
  { id: "compose", index: "03", eyebrow: "方案生成", title: "让每一次生成，\n都有设计依据。", description: "AI 联合推演布局、材质、色彩和家具组合，并保留可继续修改的空间场景。", metric: { value: "可迭代", label: "方案状态" }, annotations: ["风格组合", "动线校验", "采光分析"] },
  { id: "deliver", index: "04", eyebrow: "清单交付", title: "从灵感画面，\n走到可核验清单。", description: "方案连接目录商品、尺寸与报价，生成可沟通、可复核的提案。", metric: { value: "可追溯", label: "方案与目录数据" }, annotations: ["目录 SKU", "分项预算", "版本化提案"] },
] as const;

export function getHomeExperienceStep(index: number): HomeExperienceStep {
  return HOME_EXPERIENCE_STEPS[index] ?? HOME_EXPERIENCE_STEPS[0];
}
