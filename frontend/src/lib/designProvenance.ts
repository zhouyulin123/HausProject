const SOURCE_LABELS: Readonly<Record<string, string>> = {
  llm: "AI 模型生成",
  template: "系统模板生成",
  agent: "AI 智能体编辑",
  refine: "AI 智能体精修",
  workspace_edit: "用户编辑版本",
  demo: "Demo 演示数据",
};

export function getDesignSourceLabel(source?: string): string {
  if (!source) return "来源未知";
  return SOURCE_LABELS[source] ?? "来源未知";
}
