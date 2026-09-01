import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ChatMessage } from "@/types/chat";
import type { RoomModel } from "@/types/roomModel";
import {
  createDesignProject,
  type DesignProject,
  type DesignProjectMode,
  type DesignProjectSeed,
} from "@/lib/designProject";

interface DesignProjectState {
  projects: Record<string, DesignProject>;
  currentProjectId: string | null;
  createProject: (mode: DesignProjectMode, seed: DesignProjectSeed) => string;
  selectProject: (projectId: string) => void;
  setMessages: (projectId: string, messages: ChatMessage[]) => void;
  toggleFurniture: (projectId: string, furnitureId: string) => void;
  setRoomModel: (projectId: string, roomModel: RoomModel | null) => void;
  attachBackendTask: (
    projectId: string,
    taskId: number,
    plan?: { id: string; planVersionId?: number },
  ) => void;
}

function updateProject(
  state: DesignProjectState,
  projectId: string,
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
      createProject: (mode, seed) => {
        const project = createDesignProject(mode, seed);
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
      setRoomModel: (projectId, roomModel) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            roomModel: roomModel ? structuredClone(roomModel) : null,
          })),
        ),
      attachBackendTask: (projectId, taskId, plan) =>
        set((state) =>
          updateProject(state, projectId, (project) => ({
            ...project,
            backendTaskId: taskId,
            activePlanId: plan?.id ?? project.activePlanId,
            activePlanVersionId:
              plan?.planVersionId ?? project.activePlanVersionId,
            status: plan ? "ready" : "designing",
          })),
        ),
    }),
    {
      name: "ai-home-design-projects",
      partialize: (state) => ({
        projects: state.projects,
        currentProjectId: state.currentProjectId,
      }),
    },
  ),
);
