import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { RoomModel } from "@/types/roomModel";

interface RoomModelState {
  /** VL 识别 + 用户校准后的空间事实模型；无图或降级时为 null */
  roomModel: RoomModel | null;
  setRoomModel: (roomModel: RoomModel | null) => void;
  reset: () => void;
}

export const useRoomModelStore = create<RoomModelState>()(
  persist(
    (set) => ({
      roomModel: null,
      setRoomModel: (roomModel) => set({ roomModel }),
      reset: () => set({ roomModel: null }),
    }),
    { name: "ai-home-room-model" },
  ),
);
