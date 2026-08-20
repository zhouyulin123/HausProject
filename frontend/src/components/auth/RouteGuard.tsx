import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore";

function LoadingGate({ children }: { children: ReactElement }) {
  const initialized = useAuthStore((s) => s.initialized);
  if (!initialized) return null;
  return children;
}

/** 需要登录才能访问；未登录跳转登录页并记录来源。 */
export function RequireAuth({ children }: { children: ReactElement }) {
  return (
    <LoadingGate>
      <RequireAuthInner>{children}</RequireAuthInner>
    </LoadingGate>
  );
}

function RequireAuthInner({ children }: { children: ReactElement }) {
  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return children;
}

/** 需要厂家或管理员身份；否则回首页。 */
export function RequireFactory({ children }: { children: ReactElement }) {
  return (
    <LoadingGate>
      <RequireFactoryInner>{children}</RequireFactoryInner>
    </LoadingGate>
  );
}

function RequireFactoryInner({ children }: { children: ReactElement }) {
  const user = useAuthStore((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "factory" && user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return children;
}

/** 仅管理员可访问；否则回首页。 */
export function RequireAdmin({ children }: { children: ReactElement }) {
  return (
    <LoadingGate>
      <RequireAdminInner>{children}</RequireAdminInner>
    </LoadingGate>
  );
}

function RequireAdminInner({ children }: { children: ReactElement }) {
  const user = useAuthStore((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return children;
}
