// The FastAPI backend (src/API.md). Same exports as `mock-api.ts`, so hooks can switch between them.

import { getToken, setToken } from "@/lib/auth";
import type {
  Business,
  BusinessPatch,
  Conversation,
  ConversationMessage,
  Me,
  MenuItem,
  MenuItemInput,
  Order,
  ServerEvent,
} from "@/lib/types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Body = { json: unknown } | { form: URLSearchParams | FormData } | undefined;

async function request<T>(method: string, path: string, body?: Body): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body && "json" in body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body.json);
  } else if (body) {
    payload = body.form; // the browser sets the form content type (and multipart boundary)
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (res.status === 401 && token) setToken(null); // expired or revoked: back to /login
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    return typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
  } catch {
    return res.statusText;
  }
}

// ---------------------------------------------------------------------------
// Realtime: SSE at GET /api/v1/events (EventSource cannot send headers, so ?token=)

type Listener = (event: ServerEvent) => void;
const EVENT_TYPES: ServerEvent["type"][] = [
  "order.created",
  "order.updated",
  "payment.check_requested",
  "conversation.needs_owner",
];
const RECONNECT_MS = 5_000;

export function subscribeEvents(listener: Listener): () => void {
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let stopped = false;

  const connect = () => {
    const token = getToken();
    if (stopped || !token) return;
    source = new EventSource(`${API_URL}/api/v1/events?token=${encodeURIComponent(token)}`);
    for (const type of EVENT_TYPES) {
      source.addEventListener(type, (message) => {
        try {
          listener({ type, ...JSON.parse((message as MessageEvent<string>).data) } as ServerEvent);
        } catch {
          // ignore a malformed event; polling still refreshes the board
        }
      });
    }
    source.onerror = () => {
      // The browser retries dropped connections itself; a closed stream (e.g. 401) needs us.
      if (source?.readyState === EventSource.CLOSED) {
        source = null;
        retry = setTimeout(connect, RECONNECT_MS);
      }
    };
  };

  connect();
  return () => {
    stopped = true;
    clearTimeout(retry);
    source?.close();
  };
}

// ---------------------------------------------------------------------------
// Auth

export async function login(email: string, password: string) {
  const form = new URLSearchParams({ username: email.trim(), password });
  return request<{ access_token: string; token_type: "bearer" }>("POST", "/api/v1/auth/login", {
    form,
  });
}

export async function register(input: {
  email: string;
  password: string;
  full_name: string;
  business_name: string;
}): Promise<Me> {
  return request("POST", "/api/v1/auth/register", { json: input });
}

export async function getMe(): Promise<Me> {
  return request("GET", "/api/v1/auth/me");
}

// ---------------------------------------------------------------------------
// Orders (orders still being chatted are not on the board)

const BOARD_STATUSES = ["payment_check", "awaiting_payment", "approved", "cancelled"];

export async function getOrders(): Promise<Order[]> {
  const query = BOARD_STATUSES.map((s) => `status=${s}`).join("&");
  return request("GET", `/api/v1/orders?${query}&limit=200`);
}

export async function approveOrder(id: string): Promise<Order> {
  return request("POST", `/api/v1/orders/${id}/approve`);
}

export async function markNotReceived(id: string): Promise<Order> {
  return request("POST", `/api/v1/orders/${id}/not-received`);
}

export async function restoreOrder(id: string): Promise<Order> {
  return request("POST", `/api/v1/orders/${id}/restore`);
}

// ---------------------------------------------------------------------------
// Handoff: chats the AI passed to the owner. The owner answers here (sent through the bot)
// or gives the chat back to the AI.

export async function getConversations(needsOwner?: boolean): Promise<Conversation[]> {
  const query = needsOwner === undefined ? "" : `?needs_owner=${needsOwner}`;
  return request("GET", `/api/v1/conversations${query}`);
}

export async function getConversationMessages(id: string): Promise<ConversationMessage[]> {
  return request("GET", `/api/v1/conversations/${id}/messages`);
}

export async function replyToConversation(id: string, text: string): Promise<Conversation> {
  return request("POST", `/api/v1/conversations/${id}/reply`, { json: { text } });
}

export async function resumeAi(conversationId: string): Promise<void> {
  await request("POST", `/api/v1/conversations/${conversationId}/resume-ai`);
}

// ---------------------------------------------------------------------------
// Menu

export async function getMenu(): Promise<MenuItem[]> {
  return request("GET", "/api/v1/menu");
}

export async function createMenuItem(input: MenuItemInput): Promise<MenuItem> {
  return request("POST", "/api/v1/menu", { json: input });
}

export async function updateMenuItem(id: string, input: Partial<MenuItemInput>): Promise<MenuItem> {
  return request("PATCH", `/api/v1/menu/${id}`, { json: input });
}

export async function setAvailability(id: string, is_available: boolean): Promise<MenuItem> {
  return request("PATCH", `/api/v1/menu/${id}/availability`, { json: { is_available } });
}

export async function deleteMenuItem(id: string): Promise<void> {
  return request("DELETE", `/api/v1/menu/${id}`);
}

// ---------------------------------------------------------------------------
// Business settings

export async function getBusiness(): Promise<Business> {
  return request("GET", "/api/v1/business");
}

export async function patchBusiness(patch: BusinessPatch): Promise<Business> {
  return request("PATCH", "/api/v1/business", { json: patch });
}

export async function uploadPaymentQr(file: File): Promise<Business> {
  const form = new FormData();
  form.append("file", file);
  return request("POST", "/api/v1/business/payment-qr", { form });
}
