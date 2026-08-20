import { beforeEach, describe, expect, it } from "vitest";
import { roleLabel, useAuthStore } from "./useAuthStore";
import type { AuthUser } from "@/api/authApi";

function makeUser(role: AuthUser["role"]): AuthUser {
  return { id: 1, phone: "13800000000", nickname: null, avatar: null, role };
}

describe("useAuthStore 角色判断", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null });
  });

  it("roleLabel 返回中文角色名", () => {
    expect(roleLabel("admin")).toBe("管理员");
    expect(roleLabel("factory")).toBe("厂家");
    expect(roleLabel("customer")).toBe("用户");
  });

  it("isFactory 仅厂家与管理员为真", () => {
    useAuthStore.setState({ user: makeUser("customer") });
    expect(useAuthStore.getState().isFactory()).toBe(false);

    useAuthStore.setState({ user: makeUser("factory") });
    expect(useAuthStore.getState().isFactory()).toBe(true);

    useAuthStore.setState({ user: makeUser("admin") });
    expect(useAuthStore.getState().isFactory()).toBe(true);
  });

  it("isAdmin 仅管理员为真", () => {
    useAuthStore.setState({ user: makeUser("factory") });
    expect(useAuthStore.getState().isAdmin()).toBe(false);

    useAuthStore.setState({ user: makeUser("admin") });
    expect(useAuthStore.getState().isAdmin()).toBe(true);
  });
});
