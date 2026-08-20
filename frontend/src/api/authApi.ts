/**
 * 认证 API：手机号验证码登录/注册二合一 + 当前用户查询。
 * 独立于 designApi（匿名会话），使用 Bearer JWT 鉴权。
 */

import { readSessionId } from "./sessionStorage";

export type UserRole = "customer" | "factory" | "admin";

export interface AuthUser {
  id: number;
  phone: string | null;
  nickname: string | null;
  avatar: string | null;
  role: UserRole;
}

export interface LoginResult {
  token: string;
  user: AuthUser;
}

export class AuthApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const TOKEN_KEY = "haus-auth-token";
const USER_KEY = "haus-auth-user";

const browserStorage =
  typeof window !== "undefined" ? window.localStorage : null;

export function readToken(): string | null {
  return browserStorage ? browserStorage.getItem(TOKEN_KEY) : null;
}

export function writeToken(token: string | null): void {
  if (!browserStorage) return;
  if (token) browserStorage.setItem(TOKEN_KEY, token);
  else browserStorage.removeItem(TOKEN_KEY);
}

export function readStoredUser(): AuthUser | null {
  if (!browserStorage) return null;
  try {
    const raw = browserStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function writeStoredUser(user: AuthUser | null): void {
  if (!browserStorage) return;
  if (user) browserStorage.setItem(USER_KEY, JSON.stringify(user));
  else browserStorage.removeItem(USER_KEY);
}

async function authRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    let message = `${path} -> ${resp.status}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      /* 保留默认 message */
    }
    throw new AuthApiError(message, resp.status);
  }
  return resp.json() as Promise<T>;
}

export async function sendSmsCode(
  phone: string,
): Promise<{ status: string; dev_code?: string }> {
  return authRequest<{ status: string; dev_code?: string }>(
    "/api/auth/send-code",
    { method: "POST", body: JSON.stringify({ phone }) },
  );
}

export async function login(phone: string, code: string): Promise<LoginResult> {
  const sessionId = browserStorage ? readSessionId(browserStorage) : null;
  return authRequest<LoginResult>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ phone, code, session_id: sessionId }),
  });
}

export async function fetchMe(): Promise<AuthUser> {
  const data = await authRequest<{ user: AuthUser }>("/api/auth/me");
  return data.user;
}
