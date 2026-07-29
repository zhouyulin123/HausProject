import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { DesignPlan, SavedDesign, SavedDesignStatus } from "@/types/design";

interface DesignState {
  /** 当前匿名会话生成的方案；本地保留一份用于刷新后立即恢复展示。 */
  generatedPlans: DesignPlan[];
  setGeneratedPlans: (plans: DesignPlan[]) => void;

  /** 用户保存的方案（持久化到 localStorage） */
  savedDesigns: SavedDesign[];
  saveDesign: (plan: DesignPlan, rooms: string[]) => void;
  removeDesign: (id: string) => void;
  updateDesignStatus: (id: string, status: SavedDesignStatus) => void;
  toggleDesignFavorite: (id: string) => void;

  /** 收藏的家具 */
  favoriteFurnitureIds: string[];
  toggleFurnitureFavorite: (id: string) => void;

  /** 加入当前方案的家具 */
  pickedFurnitureIds: string[];
  togglePickedFurniture: (id: string) => void;
}

export const useDesignStore = create<DesignState>()(
  persist(
    (set, get) => ({
      generatedPlans: [],
      setGeneratedPlans: (plans) => set({ generatedPlans: plans }),

      savedDesigns: [],
      saveDesign: (plan, rooms) => {
        if (get().savedDesigns.some((d) => d.planId === plan.id)) return;
        const saved: SavedDesign = {
          id: `saved-${Date.now()}`,
          planId: plan.id,
          name: plan.name,
          style: plan.style,
          budget: plan.budget,
          rooms: rooms.length > 0 ? rooms : ["全屋"],
          status: "已生成",
          isFavorite: false,
          createdAt: new Date().toISOString().slice(0, 10),
          coverGradient: plan.coverGradient,
        };
        set((state) => ({ savedDesigns: [saved, ...state.savedDesigns] }));
      },
      removeDesign: (id) =>
        set((state) => ({
          savedDesigns: state.savedDesigns.filter((d) => d.id !== id),
        })),
      updateDesignStatus: (id, status) =>
        set((state) => ({
          savedDesigns: state.savedDesigns.map((d) =>
            d.id === id ? { ...d, status } : d,
          ),
        })),
      toggleDesignFavorite: (id) =>
        set((state) => ({
          savedDesigns: state.savedDesigns.map((d) =>
            d.id === id ? { ...d, isFavorite: !d.isFavorite } : d,
          ),
        })),

      favoriteFurnitureIds: [],
      toggleFurnitureFavorite: (id) =>
        set((state) => ({
          favoriteFurnitureIds: state.favoriteFurnitureIds.includes(id)
            ? state.favoriteFurnitureIds.filter((f) => f !== id)
            : [...state.favoriteFurnitureIds, id],
        })),

      pickedFurnitureIds: [],
      togglePickedFurniture: (id) =>
        set((state) => ({
          pickedFurnitureIds: state.pickedFurnitureIds.includes(id)
            ? state.pickedFurnitureIds.filter((f) => f !== id)
            : [...state.pickedFurnitureIds, id],
        })),
    }),
    {
      name: "ai-home-designs",
      partialize: (state) => ({
        generatedPlans: state.generatedPlans,
        savedDesigns: state.savedDesigns,
        favoriteFurnitureIds: state.favoriteFurnitureIds,
        pickedFurnitureIds: state.pickedFurnitureIds,
      }),
    },
  ),
);
