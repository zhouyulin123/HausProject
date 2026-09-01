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
  { id: "scan", index: "01", eyebrow: "空间感知", title: "先读懂空间，\n再谈风格。", description: "识别墙体、门窗、采光与可用尺度，把一张房间照片还原成可推演的数字空间。", metric: { value: "28s", label: "完成空间初步解析" }, annotations: ["南向自然光", "主通道 960mm", "承重墙已锁定"] },
  { id: "understand", index: "02", eyebrow: "生活建模", title: "设计围绕生活，\n而不是效果图。", description: "把预算、家庭成员、宠物、收纳与日常习惯转换成清晰的设计约束。", metric: { value: "12+", label: "生活维度同步分析" }, annotations: ["三口之家", "有宠物", "高收纳需求"] },
  { id: "compose", index: "03", eyebrow: "方案生成", title: "让每一次生成，\n都有设计依据。", description: "AI 联合推演布局、材质、色彩和家具组合，并保留可继续修改的空间场景。", metric: { value: "3×", label: "并行生成差异化方案" }, annotations: ["奶油原木", "动线优化 +18%", "采光利用 +23%"] },
  { id: "deliver", index: "04", eyebrow: "真实交付", title: "从灵感画面，\n走到可执行清单。", description: "方案连接真实商品、尺寸与报价，生成可沟通、可采购、可落地的完整提案。", metric: { value: "1:1", label: "方案与商品数据关联" }, annotations: ["真实 SKU", "分项预算", "品牌提案 PDF"] },
] as const;

export function getHomeExperienceStep(index: number): HomeExperienceStep {
  return HOME_EXPERIENCE_STEPS[index] ?? HOME_EXPERIENCE_STEPS[0];
}
