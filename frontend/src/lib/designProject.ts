import type { ChatMessage } from "@/types/chat";
import type { DesignPlan } from "@/types/design";
import type { FurnitureItem } from "@/types/furniture";
import type { UserRequirement } from "@/types/requirement";
import type { RoomModel } from "@/types/roomModel";

export type DesignProjectMode = "catalog" | "custom" | "scan";
export type DesignProjectStatus = "draft" | "designing" | "ready";

export interface DesignProject {
  id: string;
  mode: DesignProjectMode;
  title: string;
  status: DesignProjectStatus;
  createdAt: string;
  updatedAt: string;
  requirement: UserRequirement;
  roomModel: RoomModel | null;
  messages: ChatMessage[];
  selectedFurnitureIds: string[];
  backendTaskId: number | null;
  activePlanId: string | null;
  activePlanVersionId: number | null;
}

export interface DesignProjectSeed {
  requirement: UserRequirement;
  roomModel: RoomModel | null;
}

export interface DesignEntryMode {
  id: DesignProjectMode;
  index: string;
  title: string;
  shortTitle: string;
  description: string;
  opening: string;
}

export const DESIGN_ENTRY_MODES: readonly DesignEntryMode[] = [
  {
    id: "catalog",
    index: "01",
    title: "用现有家具搭配空间",
    shortTitle: "商品搭配",
    description: "从真实家具库筛选尺寸、预算和风格合适的商品，并直接放进房间。",
    opening:
      "我们从现有家具开始。告诉我需要设计哪个空间、预算范围，以及哪些家具必须保留；我会先补齐关键约束，再从商品库选择并摆放。",
  },
  {
    id: "custom",
    index: "02",
    title: "对话定制一件家具",
    shortTitle: "家具定制",
    description: "从用途和尺寸开始，让 AI 逐步形成可编辑、可报价的参数化家具草案。",
    opening:
      "我们来定义一件自定义家具。先告诉我它的用途、准备放在哪里，以及大致尺寸；我会逐项确认结构、材料和预算。",
  },
  {
    id: "scan",
    index: "03",
    title: "导入房间并建立 3D",
    shortTitle: "房间重建",
    description: "上传户型图或房间照片，确认尺度和门窗后，在数字房间中继续设计。",
    opening:
      "我们先建立可设计的数字房间。请上传户型图或房间照片；识别后我会请你确认尺度、门窗和固定障碍，再开始布置。",
  },
] as const;

function cloneRequirement(requirement: UserRequirement): UserRequirement {
  return {
    ...requirement,
    rooms: [...requirement.rooms],
    styles: [...requirement.styles],
    colors: [...requirement.colors],
    dislikedColors: [...requirement.dislikedColors],
    materials: [...requirement.materials],
  };
}

function createProjectId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `project-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createDesignProject(
  mode: DesignProjectMode,
  seed: DesignProjectSeed,
  options: { id?: string; now?: string } = {},
): DesignProject {
  const entry = DESIGN_ENTRY_MODES.find((item) => item.id === mode);
  if (!entry) throw new Error(`不支持的设计入口：${mode}`);

  const now = options.now ?? new Date().toISOString();
  return {
    id: options.id ?? createProjectId(),
    mode,
    title: `${entry.shortTitle} · ${new Date(now).toLocaleDateString("zh-CN")}`,
    status: "draft",
    createdAt: now,
    updatedAt: now,
    requirement: cloneRequirement(seed.requirement),
    roomModel: seed.roomModel ? structuredClone(seed.roomModel) : null,
    messages: [{ id: `opening-${options.id ?? now}`, role: "ai", content: entry.opening }],
    selectedFurnitureIds: [],
    backendTaskId: null,
    activePlanId: null,
    activePlanVersionId: null,
  };
}

export function designWorkspacePath(projectId: string): string {
  return `/design/${encodeURIComponent(projectId)}/workspace`;
}

function estimateBudget(budgetRange: string): number {
  if (budgetRange.includes("30 万")) return 300000;
  if (budgetRange.includes("15-30")) return 220000;
  if (budgetRange.includes("8-15")) return 120000;
  if (budgetRange.includes("3-8")) return 60000;
  if (budgetRange.includes("3 万以下")) return 30000;
  return 0;
}

export function buildWorkspacePlan(
  project: DesignProject,
  selectedFurniture: FurnitureItem[],
): DesignPlan {
  const entry = DESIGN_ENTRY_MODES.find((item) => item.id === project.mode)!;
  const style = project.requirement.styles[0] ?? "待确认风格";
  const room = project.requirement.rooms[0] ?? project.roomModel?.spaceType ?? "当前空间";
  return {
    id: `workspace-${project.id}`,
    planVersionId: project.activePlanVersionId ?? undefined,
    task_id: project.backendTaskId ?? undefined,
    name: project.title,
    style,
    coverGradient: "bg-gradient-to-br from-[#e5e7df] to-[#b7c2b1]",
    score: 0,
    budget: estimateBudget(project.requirement.budgetRange),
    tags: [entry.shortTitle, room],
    suitableFor: [],
    description: entry.description,
    layoutSuggestions: [],
    furnitureSuggestions: selectedFurniture,
    colorPalette: [],
    materials: [],
    lightingSuggestions: [],
    budgetBreakdown: [],
    aiTips: [],
  };
}
