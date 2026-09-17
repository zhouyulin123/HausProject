import type { ChatMessage } from "@/types/chat";
import type { DesignPlan } from "@/types/design";
import type { FurnitureItem } from "@/types/furniture";
import type { UserRequirement } from "@/types/requirement";
import type { RoomModel, RoomSource } from "@/types/roomModel";
import type { DesignScene } from "@/types/scene";
import type {
  AgentExecutionState,
  AgentExitReason,
  AgentPendingQuestion,
  AgentSceneReference,
} from "@/types/agent";
import type {
  CustomFurniturePreviewResult,
  CustomFurnitureSpecPatch,
} from "@/types/customFurniture";
import { emptyRequirement } from "@/types/requirement";

export type DesignProjectMode =
  | "catalog_design"
  | "custom_furniture"
  | "room_reconstruction";
export type DesignProjectStatus =
  | "draft"
  | "analyzing"
  | "waiting_user"
  | "ready"
  | "running"
  | "waiting_approval"
  | "completed"
  | "needs_human"
  | "failed"
  | "cancelled";

export interface CustomFurnitureDraftReference {
  clientMutationId: string;
  specSignature: string;
}

export interface DesignProject {
  /** 与后端 DesignTask.id 完全一致。 */
  id: number;
  mode: DesignProjectMode;
  title: string;
  status: DesignProjectStatus;
  createdAt: string;
  updatedAt: string;
  requirement: UserRequirement;
  roomModel: RoomModel | null;
  roomSource: RoomSource | null;
  messages: ChatMessage[];
  selectedFurnitureIds: string[];
  activeRoomId: string | null;
  stateVersion: number;
  pendingQuestions: AgentPendingQuestion[];
  facts: Record<string, unknown>;
  factEvidence: Record<string, Record<string, unknown>>;
  sceneRef: AgentSceneReference | null;
  authoritativeScene: DesignScene | null;
  exitReason: AgentExitReason | null;
  customFurnitureSpec: CustomFurnitureSpecPatch | null;
  customFurnitureResult: CustomFurniturePreviewResult | null;
  customFurnitureDraftReference: CustomFurnitureDraftReference | null;
  approvalRequired: boolean;
  generationRunId: number | null;
  execution: AgentExecutionState;
  activePlanId: string | null;
  activePlanVersionId: number | null;
}

export interface DesignProjectSeed {
  requirement: UserRequirement;
  roomModel: RoomModel | null;
  roomSource?: RoomSource | null;
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
    id: "catalog_design",
    index: "01",
    title: "用现有家具搭配空间",
    shortTitle: "商品搭配",
    description: "从真实家具库筛选尺寸、预算和风格合适的商品，并直接放进房间。",
    opening:
      "我们从现有家具开始。告诉我需要设计哪个空间、预算范围，以及哪些家具必须保留；我会先补齐关键约束，再从商品库选择并摆放。",
  },
  {
    id: "custom_furniture",
    index: "02",
    title: "对话定制一件家具",
    shortTitle: "家具定制",
    description: "从用途和尺寸开始，让 AI 逐步形成可编辑、可报价的参数化家具草案。",
    opening:
      "我们来定义一件自定义家具。先告诉我它的用途、准备放在哪里，以及大致尺寸；我会逐项确认结构、材料和预算。",
  },
  {
    id: "room_reconstruction",
    index: "03",
    title: "导入房间并建立 3D",
    shortTitle: "房间重建",
    description: "上传户型图或房间照片，确认尺度和门窗后，在数字房间中继续设计。",
    opening:
      "我们先建立可设计的数字房间。请上传户型图或房间照片；识别后我会请你确认尺度、门窗和固定障碍，再开始布置。",
  },
] as const;

export function createEmptyAgentExecutionState(): AgentExecutionState {
  return {
    currentNode: "idle",
    stepCount: 0,
    retryCount: 0,
    maxSteps: 12,
    maxRetries: 2,
    hardErrors: [],
    costCny: null,
    costReservedCny: 0,
    costLimitCny: null,
    executionDeadlineAt: null,
    cancelRequestedAt: null,
    turnExecutionDeadlineAt: null,
    events: [],
  };
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/** 用服务端事实重建浏览器已丢失的项目骨架，不推测不存在的业务字段。 */
export function restoreDesignProjectSeed(input: {
  confirmedRequirement: Record<string, unknown>;
  facts: Record<string, unknown>;
  roomModel: RoomModel | null;
  roomSource?: RoomSource | null;
}): DesignProjectSeed {
  const source = input.confirmedRequirement;
  const rooms = stringList(source.rooms);
  const styles = stringList(source.styles);
  const factSpaceType = stringValue(input.facts.space_type, "").trim();
  const factStyle = stringValue(input.facts.style, "").trim();
  const area = source.area;
  const familySize = source.familySize;
  return {
    requirement: {
      ...emptyRequirement,
      rooms: rooms.length
        ? rooms
        : factSpaceType
          ? [factSpaceType]
          : input.roomModel?.spaceType
            ? [input.roomModel.spaceType]
            : [],
      area: typeof area === "number" && Number.isFinite(area) ? area : null,
      houseType: stringValue(source.houseType, emptyRequirement.houseType),
      city: stringValue(source.city, emptyRequirement.city),
      renovationType: stringValue(
        source.renovationType,
        emptyRequirement.renovationType,
      ),
      budgetRange: stringValue(source.budgetRange, emptyRequirement.budgetRange),
      familySize:
        typeof familySize === "number" && Number.isFinite(familySize)
          ? familySize
          : emptyRequirement.familySize,
      hasElderly: booleanValue(source.hasElderly, emptyRequirement.hasElderly),
      hasChildren: booleanValue(source.hasChildren, emptyRequirement.hasChildren),
      hasPets: booleanValue(source.hasPets, emptyRequirement.hasPets),
      workFromHome: booleanValue(source.workFromHome, emptyRequirement.workFromHome),
      cookingOften: booleanValue(source.cookingOften, emptyRequirement.cookingOften),
      needStorage: booleanValue(source.needStorage, emptyRequirement.needStorage),
      ecoFriendly: booleanValue(source.ecoFriendly, emptyRequirement.ecoFriendly),
      smartHome: booleanValue(source.smartHome, emptyRequirement.smartHome),
      styles: styles.length ? styles : factStyle ? [factStyle] : [],
      colors: stringList(source.colors),
      dislikedColors: stringList(source.dislikedColors),
      materials: stringList(source.materials),
      extraNotes: stringValue(source.extraNotes, emptyRequirement.extraNotes),
    },
    roomModel: input.roomModel ? structuredClone(input.roomModel) : null,
    roomSource: input.roomModel && input.roomSource ? structuredClone(input.roomSource) : null,
  };
}

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

export function createDesignProject(
  mode: DesignProjectMode,
  seed: DesignProjectSeed,
  options: { id: number; now?: string },
): DesignProject {
  const entry = DESIGN_ENTRY_MODES.find((item) => item.id === mode);
  if (!entry) throw new Error(`不支持的设计入口：${mode}`);

  const now = options.now ?? new Date().toISOString();
  return {
    id: options.id,
    mode,
    title: `${entry.shortTitle} · ${new Date(now).toLocaleDateString("zh-CN")}`,
    status: "draft",
    createdAt: now,
    updatedAt: now,
    requirement: cloneRequirement(seed.requirement),
    roomModel: seed.roomModel ? structuredClone(seed.roomModel) : null,
    roomSource: seed.roomModel && seed.roomSource ? structuredClone(seed.roomSource) : null,
    messages: [{ id: `opening-${options.id}`, role: "ai", content: entry.opening }],
    selectedFurnitureIds: [],
    activeRoomId: seed.roomModel?.rooms[0]?.id ?? null,
    stateVersion: 0,
    pendingQuestions: [],
    facts: {},
    factEvidence: {},
    sceneRef: null,
    authoritativeScene: null,
    exitReason: null,
    customFurnitureSpec: null,
    customFurnitureResult: null,
    customFurnitureDraftReference: null,
    approvalRequired: false,
    generationRunId: null,
    execution: createEmptyAgentExecutionState(),
    activePlanId: null,
    activePlanVersionId: null,
  };
}

export function designWorkspacePath(projectId: number): string {
  return `/design/${projectId}/workspace`;
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
    task_id: project.id,
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
