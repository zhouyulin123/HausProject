import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatMessage } from "@/types/chat";
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
import {
  createEmptyAgentExecutionState,
  createDesignProject,
  type CustomFurnitureDraftReference,
  type DesignProject,
  type DesignProjectMode,
  type DesignProjectSeed,
} from "@/lib/designProject";

interface DesignProjectState {
  projects: Record<string, DesignProject>;
  currentProjectId: number | null;
  registerProject: (
    taskId: number,
    mode: DesignProjectMode,
    seed: DesignProjectSeed,
  ) => number;
  selectProject: (projectId: number) => void;
  setMessages: (projectId: number, messages: ChatMessage[]) => void;
  toggleFurniture: (projectId: number, furnitureId: string) => void;
  setFurnitureSelection: (projectId: number, furnitureIds: string[]) => void;
  replaceFurniture: (
    projectId: number,
    sourceFurnitureId: string,
    targetFurnitureId: string,
  ) => boolean;
  setRoomModel: (projectId: number, roomModel: RoomModel | null) => void;
  setRoomContext: (
    projectId: number,
    context: { roomModel: RoomModel | null; roomSource: RoomSource | null },
  ) => void;
  setSceneReference: (
    projectId: number,
    sceneRef: AgentSceneReference | null,
  ) => void;
  setAuthoritativeScene: (
    projectId: number,
    scene: DesignScene | null,
  ) => void;
  setCustomFurnitureDraftReference: (
    projectId: number,
    reference: CustomFurnitureDraftReference | null,
    stateVersion?: number,
  ) => void;
  attachPlan: (
    projectId: number,
    plan?: { id: string; planVersionId?: number },
  ) => void;
  applyAgentState: (
    projectId: number,
    checkpoint: {
      stateVersion: number;
      status: DesignProject["status"];
      activeMode: DesignProjectMode;
      pendingQuestions: AgentPendingQuestion[];
      facts?: Record<string, unknown>;
      factEvidence?: Record<string, Record<string, unknown>>;
      roomContext?: { roomModel: RoomModel | null; roomSource: RoomSource | null };
      sceneRef: AgentSceneReference | null;
      exitReason: AgentExitReason | null;
      activeRoomId?: string | null;
      customFurnitureSpec?: CustomFurnitureSpecPatch | null;
      customFurnitureResult?: CustomFurniturePreviewResult | null;
      approvalRequired?: boolean;
      generationRunId?: number | null;
      execution?: AgentExecutionState;
    },
  ) => void;
}

export function migrateDesignProjectState(persisted: unknown, _version?: number): {
  projects: Record<string, DesignProject>;
  currentProjectId: number | null;
} {
  const state = persisted as Partial<DesignProjectState>;
  return {
    projects: Object.fromEntries(
      Object.entries(state.projects ?? {}).map(([id, project]) => [
        id,
        {
          ...project,
          messages: [],
          facts: project.facts ?? {},
          factEvidence: project.factEvidence ?? {},
          roomSource: project.roomModel ? project.roomSource ?? null : null,
          customFurnitureSpec: null,
          customFurnitureResult: null,
          authoritativeScene: null,
          customFurnitureDraftReference:
            project.customFurnitureDraftReference ?? null,
          approvalRequired: false,
          generationRunId: project.generationRunId ?? null,
          execution: project.execution ?? createEmptyAgentExecutionState(),
        },
      ]),
    ),
    currentProjectId: state.currentProjectId ?? null,
  };
}

function updateProject(
  state: DesignProjectState,
  projectId: number,
  update: (project: DesignProject) => DesignProject,
): Pick<DesignProjectState, "projects"> {
  const project = state.projects[projectId];
  if (!project) return { projects: state.projects };
  const updatedProject = update(project);
  if (updatedProject === project) return { projects: state.projects };
  return {
    projects: {
      ...state.projects,
      [projectId]: {
        ...updatedProject,
        updatedAt: new Date().toISOString(),
      },
    },
  };
}

export const useDesignProjectStore = create<DesignProjectState>()(
  persist(
    (set) => ({
      projects: {},
      currentProjectId: null,
      registerProject: (taskId, mode, seed) => {
        const project = createDesignProject(mode, seed, { id: taskId });
        set((state) => ({
          projects: { ...state.projects, [project.id]: project },
          currentProjectId: project.id,
        }));
        return project.id;
      },
      selectProject: (projectId) =>
        set((state) =>
          state.projects[projectId] ? { currentProjectId: projectId } : state,
        ),
      setMessages: (projectId, messages) =>
        set((state) =>
          updateProject(state, projectId, () => ({
            ...state.projects[projectId]!,
            messages: messages.map((message) => ({ ...message })),
          })),
        ),
      toggleFurniture: (projectId, furnitureId) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            selectedFurnitureIds: project.selectedFurnitureIds.includes(furnitureId)
              ? project.selectedFurnitureIds.filter((id) => id !== furnitureId)
              : [...project.selectedFurnitureIds, furnitureId],
          })),
        ),
      setFurnitureSelection: (projectId, furnitureIds) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            selectedFurnitureIds: [...new Set(furnitureIds)],
          })),
        ),
      replaceFurniture: (projectId, sourceFurnitureId, targetFurnitureId) => {
        let replaced = false;
        set((state) => {
          const project = state.projects[projectId];
          if (
            !project
            || sourceFurnitureId === targetFurnitureId
            || !project.selectedFurnitureIds.includes(sourceFurnitureId)
            || project.selectedFurnitureIds.includes(targetFurnitureId)
          ) return state;
          replaced = true;
          return updateProject(state, projectId, (current) => ({
            ...current,
            selectedFurnitureIds: current.selectedFurnitureIds.map((id) =>
              id === sourceFurnitureId ? targetFurnitureId : id,
            ),
          }));
        });
        return replaced;
      },
      setRoomModel: (projectId, roomModel) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            roomModel: roomModel ? structuredClone(roomModel) : null,
            roomSource: null,
          })),
        ),
      setRoomContext: (projectId, context) =>
        set((state) => updateProject(state, projectId, (project) => ({
          ...project,
          roomModel: context.roomModel ? structuredClone(context.roomModel) : null,
          roomSource: context.roomModel && context.roomSource
            ? structuredClone(context.roomSource) : null,
        }))),
      setSceneReference: (projectId, sceneRef) =>
        set((state) =>
          updateProject(state, projectId, (project) => {
            const current = project.sceneRef;
            if (
              current
              && sceneRef
              && current.scene_id === sceneRef.scene_id
              && current.version > sceneRef.version
            ) {
              return project;
            }
            if (
              current?.scene_id === sceneRef?.scene_id
              && current?.version === sceneRef?.version
            ) {
              return project;
            }
            return {
              ...project,
              sceneRef,
              authoritativeScene:
                project.authoritativeScene
                && sceneRef
                && project.authoritativeScene.id === sceneRef.scene_id
                && project.authoritativeScene.current_version >= sceneRef.version
                  ? project.authoritativeScene
                  : null,
            };
          }),
        ),
      setAuthoritativeScene: (projectId, scene) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            authoritativeScene: scene,
            sceneRef: scene
              ? { scene_id: scene.id, version: scene.current_version }
              : project.sceneRef,
          })),
        ),
      setCustomFurnitureDraftReference: (projectId, reference, stateVersion) =>
        set((state) =>
          updateProject(state, projectId, (project) => {
            if (stateVersion !== undefined && stateVersion < project.stateVersion) {
              return project;
            }
            return {
              ...project,
              stateVersion:
                stateVersion === undefined
                  ? project.stateVersion
                  : Math.max(project.stateVersion, stateVersion),
              customFurnitureDraftReference: reference
                ? { ...reference }
                : null,
            };
          }),
        ),
      attachPlan: (projectId, plan) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            activePlanId: plan?.id ?? project.activePlanId,
            activePlanVersionId:
              plan?.planVersionId ?? project.activePlanVersionId,
            status: plan
              ? project.status === "completed" ? "completed" : "ready"
              : "running",
          })),
        ),
      applyAgentState: (projectId, checkpoint) =>
        set((state) =>
          updateProject(state, projectId, (project) => {
            if (checkpoint.stateVersion < project.stateVersion) return project;
            // 上传记录只追加，服务端按最新有效图片 ID 选择空间上下文。
            const incomingRoom = checkpoint.roomContext;
            const roomContext = incomingRoom && (
              !project.roomSource
              || (incomingRoom.roomSource
                && incomingRoom.roomSource.image_id >= project.roomSource.image_id)
            ) ? incomingRoom : undefined;
            return {
              ...project,
              ...(roomContext ? {
                roomModel: roomContext.roomModel
                  ? structuredClone(roomContext.roomModel) : null,
                roomSource: roomContext.roomModel && roomContext.roomSource
                  ? structuredClone(roomContext.roomSource) : null,
              } : {}),
              status: checkpoint.status,
              mode: checkpoint.activeMode,
              stateVersion: checkpoint.stateVersion,
              pendingQuestions: checkpoint.pendingQuestions,
              facts: checkpoint.facts
                ? structuredClone(checkpoint.facts)
                : project.facts,
              factEvidence: checkpoint.factEvidence
                ? structuredClone(checkpoint.factEvidence)
                : project.factEvidence,
              sceneRef:
                project.sceneRef
                && checkpoint.sceneRef
                && project.sceneRef.scene_id === checkpoint.sceneRef.scene_id
                && project.sceneRef.version > checkpoint.sceneRef.version
                  ? project.sceneRef
                  : checkpoint.sceneRef ?? project.sceneRef,
              exitReason: checkpoint.exitReason,
              activeRoomId:
                checkpoint.activeRoomId === undefined
                  ? project.activeRoomId
                  : checkpoint.activeRoomId,
              customFurnitureSpec:
                checkpoint.customFurnitureSpec === undefined
                  ? project.customFurnitureSpec
                  : checkpoint.customFurnitureSpec,
              customFurnitureResult:
                checkpoint.customFurnitureResult === undefined
                  ? project.customFurnitureResult
                  : checkpoint.customFurnitureResult,
              approvalRequired:
                checkpoint.approvalRequired ?? project.approvalRequired,
              generationRunId:
                checkpoint.generationRunId === undefined
                  ? project.generationRunId
                  : checkpoint.generationRunId,
              execution: checkpoint.execution ?? project.execution,
            };
          }),
        ),
    }),
    {
      name: "ai-home-design-projects",
      version: 6,
      migrate: migrateDesignProjectState,
      partialize: (state) => ({
        projects: Object.fromEntries(
          Object.entries(state.projects).map(([id, project]) => [
            id,
            {
              ...project,
              messages: [],
              customFurnitureSpec: null,
              customFurnitureResult: null,
              authoritativeScene: null,
              approvalRequired: false,
              generationRunId: project.generationRunId,
            },
          ]),
        ),
        currentProjectId: state.currentProjectId,
      }),
    },
  ),
);
