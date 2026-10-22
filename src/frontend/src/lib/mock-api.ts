// In-memory stand-in for the FastAPI backend (src/API.md), so the dashboard can be designed
// before the backend exists. Function names and shapes follow the real endpoints; swap the
// imports in src/hooks/* to the real `lib/api.ts` when it lands. State resets on page reload.
//

import {
  seedBusiness,
  seedExclusions,
  seedMenu,
  seedOrders,
  seedOwner,
} from "@/lib/mock-data";
import type {
  Business,
  BusinessPatch,
  Exclusion,
  Me,
  MenuItem,
  MenuItemInput,
  Order,
  OrderStatus,
  ServerEvent,
  WhatsAppInput,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const db = {
  password: "demo1234",
  owner: structuredClone(seedOwner),
  business: structuredClone(seedBusiness),
  menu: structuredClone(seedMenu),
  orders: structuredClone(seedOrders),
  exclusions: structuredClone(seedExclusions),
};

let seq = 1000;
const newId = (prefix: string) => `${prefix}_${++seq}`;
const wait = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms));
const clone = <T>(value: T): T => structuredClone(value);
const now = () => new Date().toISOString();
const inMinutes = (n: number) => new Date(Date.now() + n * 60_000).toISOString();
const normaliseMoney = (m: string): string => Number(m).toFixed(2);

function findOrder(id: string): Order {
  const order = db.orders.find((o) => o.id === id);
  if (!order) throw new ApiError(404, "order_not_found");
  return order;
}

function requireStatus(order: Order, status: OrderStatus) {
  if (order.status !== status) throw new ApiError(409, "invalid_transition");
}

// ---------------------------------------------------------------------------
// Realtime (stands in for the SSE stream at GET /api/v1/events)

type Listener = (event: ServerEvent) => void;
const listeners = new Set<Listener>();

export function subscribeEvents(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function emit(event: ServerEvent) {
  // Async like a real network event, so it never fires mid-render.
  setTimeout(() => listeners.forEach((listener) => listener(event)), 0);
}

// Timer job: same rule as backend services/timers.py.
function expireOverdue() {
  const t = Date.now();
  for (const order of db.orders) {
    const timed = order.status === "awaiting_payment" || order.status === "payment_check";
    if (!timed || !order.expires_at || Date.parse(order.expires_at) > t) continue;
    order.cancelled_reason = order.status === "awaiting_payment" ? "payment_timeout" : "owner_timeout";
    order.status = "cancelled";
    order.expires_at = null;
    order.updated_at = now();
    emit({ type: "order.updated", order_id: order.id });
  }
}

if (typeof window !== "undefined") {
  setInterval(expireOverdue, 5_000);
}

// ---------------------------------------------------------------------------
// Auth

export async function login(email: string, password: string) {
  await wait(400);
  if (email.trim().toLowerCase() !== db.owner.email || password !== db.password) {
    throw new ApiError(401, "invalid_credentials");
  }
  return { access_token: "mock-token", token_type: "bearer" as const };
}

export async function register(input: {
  email: string;
  password: string;
  full_name: string;
  business_name: string;
}): Promise<Me> {
  await wait(500);
  db.owner = { ...db.owner, email: input.email.trim().toLowerCase(), full_name: input.full_name };
  db.password = input.password;
  db.business = { ...db.business, name: input.business_name };
  return getMeSync();
}

function getMeSync(): Me {
  return clone({ owner: db.owner, business: db.business });
}

export async function getMe(): Promise<Me> {
  await wait(150);
  return getMeSync();
}

// ---------------------------------------------------------------------------
// Orders

export async function getOrders(): Promise<Order[]> {
  await wait();
  expireOverdue();
  return clone(
    db.orders
      .filter((o) => o.status !== "chatting")
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  );
}

export async function approveOrder(id: string): Promise<Order> {
  await wait(400);
  const order = findOrder(id);
  if (order.status === "approved") return clone(order); // repeated clicks are safe
  requireStatus(order, "payment_check");
  order.status = "approved";
  order.approved_at = now();
  order.expires_at = null;
  order.updated_at = now();
  emit({ type: "order.updated", order_id: id });
  return clone(order);
}

export async function markNotReceived(id: string): Promise<Order> {
  await wait(400);
  const order = findOrder(id);
  requireStatus(order, "payment_check");
  order.status = "awaiting_payment";
  order.expires_at = inMinutes(db.business.payment_timeout_minutes);
  order.updated_at = now();
  emit({ type: "order.updated", order_id: id });
  return clone(order);
}

export async function restoreOrder(id: string): Promise<Order> {
  await wait(400);
  const order = findOrder(id);
  requireStatus(order, "cancelled");
  order.status = "payment_check";
  order.cancelled_reason = null;
  order.expires_at = inMinutes(db.business.payment_timeout_minutes);
  order.updated_at = now();
  emit({ type: "order.updated", order_id: id });
  return clone(order);
}

/** Dev helper: the newest awaiting order's customer says "paid" and sends a screenshot. */
export async function simulateCustomerPaid(): Promise<Order | null> {
  await wait(300);
  const order = db.orders
    .filter((o) => o.status === "awaiting_payment")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  if (!order) return null;
  markPaidByCustomer(order, "/mock/receipt-1.svg");
  return clone(order);
}

function markPaidByCustomer(order: Order, proofUrl: string | null) {
  order.status = "payment_check";
  order.payment_proof_media_url = proofUrl ?? order.payment_proof_media_url;
  order.expires_at = inMinutes(db.business.payment_timeout_minutes);
  order.updated_at = now();
  emit({ type: "payment.check_requested", order_id: order.id });
}

// ---------------------------------------------------------------------------
// Menu

export async function getMenu(): Promise<MenuItem[]> {
  await wait();
  return clone([...db.menu].sort((a, b) => a.sort_order - b.sort_order));
}

function slugify(name: string): string {
  const base = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "item";
  let slug = base;
  for (let n = 2; db.menu.some((m) => m.slug === slug); n++) slug = `${base}_${n}`;
  return slug;
}

export async function createMenuItem(input: MenuItemInput): Promise<MenuItem> {
  await wait(400);
  const item: MenuItem = {
    ...input,
    id: newId("mi"),
    slug: slugify(input.name),
    price: normaliseMoney(input.price),
    sort_order: Math.max(0, ...db.menu.map((m) => m.sort_order)) + 1,
  };
  db.menu.push(item);
  return clone(item);
}

export async function updateMenuItem(id: string, input: Partial<MenuItemInput>): Promise<MenuItem> {
  await wait(400);
  const item = db.menu.find((m) => m.id === id);
  if (!item) throw new ApiError(404, "menu_item_not_found");
  Object.assign(item, input, input.price ? { price: normaliseMoney(input.price) } : {});
  return clone(item);
}

export async function setAvailability(id: string, is_available: boolean): Promise<MenuItem> {
  return updateMenuItem(id, { is_available });
}

export async function deleteMenuItem(id: string): Promise<void> {
  await wait(300);
  db.menu = db.menu.filter((m) => m.id !== id);
}

// ---------------------------------------------------------------------------
// Business settings

export async function getBusiness(): Promise<Business> {
  await wait();
  return clone(db.business);
}

export async function patchBusiness(patch: BusinessPatch): Promise<Business> {
  await wait(400);
  Object.assign(
    db.business,
    patch,
    patch.delivery_fee ? { delivery_fee: normaliseMoney(patch.delivery_fee) } : {},
  );
  return clone(db.business);
}

export async function uploadPaymentQr(file: File): Promise<Business> {
  await wait(600);
  db.business.payment_qr_url = URL.createObjectURL(file);
  return clone(db.business);
}

export async function putWhatsApp(input: WhatsAppInput): Promise<Business> {
  await wait(500);
  db.business.whatsapp = {
    phone_number_id: input.phone_number_id,
    display_phone: input.display_phone,
    coexistence: db.business.whatsapp?.coexistence ?? false,
  };
  return clone(db.business);
}

export async function getExclusions(): Promise<Exclusion[]> {
  await wait();
  return clone(db.exclusions);
}

export async function addExclusion(input: Omit<Exclusion, "id">): Promise<Exclusion> {
  await wait(300);
  if (db.exclusions.some((e) => e.wa_phone === input.wa_phone)) {
    throw new ApiError(409, "already_excluded");
  }
  const exclusion = { ...input, id: newId("exc") };
  db.exclusions.push(exclusion);
  return clone(exclusion);
}

export async function removeExclusion(id: string): Promise<void> {
  await wait(300);
  db.exclusions = db.exclusions.filter((e) => e.id !== id);
}
