import { create } from "zustand";
import type { ShopSettings } from "@/api/designApi";
import { fetchShopSettings } from "@/api/designApi";

interface ShopState {
  shop: ShopSettings | null;
  loaded: boolean;
  /** 拉取店铺信息（应用启动时 + 保存店铺设置后调用） */
  load: () => Promise<void>;
}

export const useShopStore = create<ShopState>((set) => ({
  shop: null,
  loaded: false,
  load: async () => {
    try {
      const shop = await fetchShopSettings();
      set({ shop, loaded: true });
    } catch {
      // 后端不可用时保持 null，页头/页脚回退到默认名
      set({ loaded: true });
    }
  },
}));
