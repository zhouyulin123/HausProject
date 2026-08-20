import { create } from "zustand";
import type { AuthUser, UserRole } from "@/api/authApi";
import {
  fetchMe,
  login as apiLogin,
  readStoredUser,
  readToken,
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
    writeToken(result.token);
    writeStoredUser(result.user);
    set({ user: result.user });
    return result.user;
  },

  init: async () => {
    if (!readToken()) {
      set({ initialized: true, user: null });
      return;
    }
    try {
      const user = await fetchMe();
      writeStoredUser(user);
      set({ user, initialized: true });
    } catch {
      // token 失效或网络异常时清空登录态，回退到未登录
      writeToken(null);
      writeStoredUser(null);
      set({ user: null, initialized: true });
    }
  },

  logout: () => {
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
