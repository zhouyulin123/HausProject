export type DesignJourneyStage = {
  path: "/customize" | "/upload" | "/chat" | "/results";
  index: string;
  label: string;
  technicalLabel: string;
  progress: 25 | 50 | 75 | 100;
};

export const DESIGN_JOURNEY: readonly DesignJourneyStage[] = [
  { path: "/customize", index: "01", label: "定义需求", technicalLabel: "BRIEF", progress: 25 },
  { path: "/upload", index: "02", label: "读取空间", technicalLabel: "VISION", progress: 50 },
  { path: "/chat", index: "03", label: "校准意图", technicalLabel: "DIALOGUE", progress: 75 },
  { path: "/results", index: "04", label: "方案推演", technicalLabel: "OUTPUT", progress: 100 },
] as const;

export function getJourneyStage(pathname: string): DesignJourneyStage {
  return DESIGN_JOURNEY.find((stage) => stage.path === pathname) ?? DESIGN_JOURNEY[0];
}
