/**
 * 订单池 API：普通用户发布订单意向，厂家接单报价，用户比价成交。
 * 需要 Bearer JWT 鉴权。
 */

import { readToken } from "./authApi";
import { useAuthStore } from "@/store/useAuthStore";

export type OrderStatus =
  | "open"
  | "quoted"
  | "assigned"
  | "closed"
  | "cancelled";

export interface OrderQuote {
  id: number;
  order_id: number;
  factory_id: number;
  factory_name: string | null;
  total_price: number;
  price_min: number | null;
  price_max: number | null;
  note: string | null;
  status: "pending" | "accepted" | "rejected";
  created_at: string | null;
}

export interface Order {
  id: number;
  order_no: string;
  customer_id: number;
  source_type: "plan" | "requirement";
  task_id: number | null;
  plan_version_id: number | null;
  title: string | null;
  description: string | null;
  budget_min: number | null;
  budget_max: number | null;
  status: OrderStatus;
  assigned_factory_id: number | null;
  assigned_quote_id: number | null;
  created_at: string | null;
  customer_name?: string | null;
  pending_quote_count?: number;
  quotes?: OrderQuote[];
}

export class OrderApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function orderRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    if (resp.status === 401) {
      // token 失效，立即清空登录态，下次导航会引导重新登录
      useAuthStore.getState().logout();
    }
    let message = `${path} -> ${resp.status}`;
    try {
      const body = (await resp.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      /* 保留默认 message */
    }
    throw new OrderApiError(message, resp.status);
  }
  return resp.json() as Promise<T>;
}

export interface OrderCreatePayload {
  source_type: "plan" | "requirement";
  task_id?: number | null;
  plan_version_id?: number | null;
  title?: string;
  description?: string;
  budget_min?: number;
  budget_max?: number;
}

export async function createOrder(
  payload: OrderCreatePayload,
): Promise<Order> {
  const data = await orderRequest<{ order: Order }>("/api/orders", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return data.order;
}

export async function listMyOrders(): Promise<Order[]> {
  const data = await orderRequest<{ orders: Order[] }>("/api/orders/mine");
  return data.orders;
}

export async function fetchUnreadQuoteCount(): Promise<number> {
  const data = await orderRequest<{ count: number }>("/api/orders/unread-count");
  return data.count;
}

export async function listOrderPool(status?: OrderStatus): Promise<Order[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  const data = await orderRequest<{ orders: Order[] }>(`/api/orders${query}`);
  return data.orders;
}

export async function getOrder(orderId: number): Promise<Order> {
  const data = await orderRequest<{ order: Order }>(`/api/orders/${orderId}`);
  return data.order;
}

export async function addQuote(
  orderId: number,
  payload: { total_price: number; note?: string },
): Promise<OrderQuote> {
  const data = await orderRequest<{ quote: OrderQuote }>(
    `/api/orders/${orderId}/quotes`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return data.quote;
}

export async function acceptQuote(orderId: number, quoteId: number): Promise<Order> {
  const data = await orderRequest<{ order: Order }>(
    `/api/orders/${orderId}/accept`,
    { method: "POST", body: JSON.stringify({ quote_id: quoteId }) },
  );
  return data.order;
}

export async function closeOrder(orderId: number): Promise<Order> {
  const data = await orderRequest<{ order: Order }>(
    `/api/orders/${orderId}/close`,
    { method: "POST", body: JSON.stringify({}) },
  );
  return data.order;
}

export const orderStatusLabel: Record<OrderStatus, string> = {
  open: "待报价",
  quoted: "已有报价",
  assigned: "已成交",
  closed: "已关闭",
  cancelled: "已取消",
};
