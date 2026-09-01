import { create } from "zustand";
import type { AuthUser, UserRole } from "@/api/authApi";
import {
  fetchMe,
  login as apiLogin,
  logoutSession,
  AuthApiError,
  readStoredUser,
  writeStoredUser,
  writeToken,
} from "@/api/authApi";

interface AuthState {
  user: AuthUser | null;
  initialized: boolean;
  /** 验证码登录/注册，成功后写入 token 与用户信息 */
  login: (phone: string, code: string) => Promise<AuthUser>;
  /** 应用启动时恢复登录态；有 token 则校验并拉取最新用户 */
  init: () => Promise<void>;
  logout: () => void;
  isFactory: () => boolean;
  isAdmin: () => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: readStoredUser(),
  initialized: false,

  login: async (phone, code) => {
    const result = await apiLogin(phone, code);
    // 新登录态由 HttpOnly Cookie 保存；清理旧版本遗留的 localStorage JWT。
    writeToken(null);
    writeStoredUser(result.user);
    set({ user: result.user });
    return result.user;
  },

  init: async () => {
    try {
      const user = await fetchMe();
      writeToken(null);
      writeStoredUser(user);
      set({ user, initialized: true });
    } catch (error) {
      if (error instanceof AuthApiError && [401, 403].includes(error.status)) {
        writeToken(null);
        writeStoredUser(null);
        set({ user: null, initialized: true });
        return;
      }
      // 网络或服务暂时不可用时保留缓存身份，避免一次抖动导致误登出。
      set({ user: readStoredUser(), initialized: true });
    }
  },

  logout: () => {
    void logoutSession().catch(() => undefined);
    writeToken(null);
    writeStoredUser(null);
    set({ user: null });
  },

  isFactory: () => {
    const role = get().user?.role;
    return role === "factory" || role === "admin";
  },

  isAdmin: () => get().user?.role === "admin",
}));

export function roleLabel(role: UserRole): string {
  if (role === "admin") return "管理员";
  if (role === "factory") return "厂家";
  return "用户";
}
