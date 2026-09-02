import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatMessage } from "@/types/chat";
import type { RoomModel } from "@/types/roomModel";
import type {
  AgentExitReason,
  AgentPendingQuestion,
  AgentSceneReference,
} from "@/types/agent";
import type {
  CustomFurniturePreviewResult,
  CustomFurnitureSpecPatch,
} from "@/types/customFurniture";
import {
  createDesignProject,
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
  setSceneReference: (
    projectId: number,
    sceneRef: AgentSceneReference | null,
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
      sceneRef: AgentSceneReference | null;
      exitReason: AgentExitReason | null;
      activeRoomId?: string | null;
      customFurnitureSpec?: CustomFurnitureSpecPatch | null;
      customFurnitureResult?: CustomFurniturePreviewResult | null;
      approvalRequired?: boolean;
    },
  ) => void;
}

function updateProject(
  state: DesignProjectState,
  projectId: number,
  update: (project: DesignProject) => DesignProject,
): Pick<DesignProjectState, "projects"> {
  const project = state.projects[projectId];
  if (!project) return { projects: state.projects };
  return {
    projects: {
      ...state.projects,
      [projectId]: {
        ...update(project),
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
          })),
        ),
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
            return { ...project, sceneRef };
          }),
        ),
      attachPlan: (projectId, plan) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            activePlanId: plan?.id ?? project.activePlanId,
            activePlanVersionId:
              plan?.planVersionId ?? project.activePlanVersionId,
            status: plan ? "ready" : "running",
          })),
        ),
      applyAgentState: (projectId, checkpoint) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            status: checkpoint.status,
            mode: checkpoint.activeMode,
            stateVersion: checkpoint.stateVersion,
            pendingQuestions: checkpoint.pendingQuestions,
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
          })),
        ),
    }),
    {
      name: "ai-home-design-projects",
      version: 2,
      migrate: (persisted) => {
        const state = persisted as Partial<DesignProjectState>;
        return {
          projects: Object.fromEntries(
            Object.entries(state.projects ?? {}).map(([id, project]) => [
              id,
              {
                ...project,
                messages: [],
                customFurnitureSpec: null,
                customFurnitureResult: null,
                approvalRequired: false,
              },
            ]),
          ),
          currentProjectId: state.currentProjectId ?? null,
        };
      },
      partialize: (state) => ({
        projects: Object.fromEntries(
          Object.entries(state.projects).map(([id, project]) => [
            id,
            {
              ...project,
              messages: [],
              customFurnitureSpec: null,
              customFurnitureResult: null,
              approvalRequired: false,
            },
          ]),
        ),
        currentProjectId: state.currentProjectId,
      }),
    },
  ),
);
