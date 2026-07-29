import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UserRequirement } from "@/types/requirement";
import { emptyRequirement } from "@/types/requirement";

interface RequirementState {
  requirement: UserRequirement;
  update: (patch: Partial<UserRequirement>) => void;
  toggleArrayItem: (
    field: "rooms" | "styles" | "colors" | "dislikedColors" | "materials",
    value: string,
  ) => void;
  reset: () => void;
}

export const useRequirementStore = create<RequirementState>()(
  persist(
    (set) => ({
      requirement: emptyRequirement,
      update: (patch) =>
        set((state) => ({ requirement: { ...state.requirement, ...patch } })),
      toggleArrayItem: (field, value) =>
        set((state) => {
          const list = state.requirement[field];
          const next = list.includes(value)
            ? list.filter((v) => v !== value)
            : [...list, value];
          return { requirement: { ...state.requirement, [field]: next } };
        }),
      reset: () => set({ requirement: emptyRequirement }),
    }),
    { name: "ai-home-requirement" },
  ),
);
