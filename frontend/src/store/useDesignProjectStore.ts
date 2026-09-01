import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatMessage } from "@/types/chat";
import type { RoomModel } from "@/types/roomModel";
import type {
  AgentExitReason,
  AgentPendingQuestion,
  AgentSceneReference,
} from "@/types/agent";
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
  setRoomModel: (projectId: number, roomModel: RoomModel | null) => void;
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
      setRoomModel: (projectId, roomModel) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            roomModel: roomModel ? structuredClone(roomModel) : null,
          })),
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
            sceneRef: checkpoint.sceneRef,
            exitReason: checkpoint.exitReason,
            activeRoomId:
              checkpoint.activeRoomId === undefined
                ? project.activeRoomId
                : checkpoint.activeRoomId,
          })),
        ),
    }),
    {
      name: "ai-home-design-projects",
      version: 1,
      migrate: (persisted) => {
        const state = persisted as Partial<DesignProjectState>;
        return {
          projects: Object.fromEntries(
            Object.entries(state.projects ?? {}).map(([id, project]) => [
              id,
              { ...project, messages: [] },
            ]),
          ),
          currentProjectId: state.currentProjectId ?? null,
        };
      },
      partialize: (state) => ({
        projects: Object.fromEntries(
          Object.entries(state.projects).map(([id, project]) => [
            id,
            { ...project, messages: [] },
          ]),
        ),
        currentProjectId: state.currentProjectId,
      }),
    },
  ),
);
