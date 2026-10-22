import type { OrderStatus } from "@/lib/types";

export const BOARD_COLUMNS = ["payment_check", "awaiting_payment", "approved", "cancelled"] as const;
export type BoardStatus = (typeof BOARD_COLUMNS)[number];

/** Order of statuses when sorting "by status": what needs the owner first. */
export const STATUS_ORDER: OrderStatus[] = [...BOARD_COLUMNS, "chatting"];

// Signal colors are theme tokens (see globals.css), so they adapt to light and dark.
export const statusStyle: Record<OrderStatus, { dot: string; badge: string }> = {
  chatting: { dot: "bg-status-cancelled", badge: "bg-status-cancelled-soft text-status-cancelled" },
  awaiting_payment: { dot: "bg-status-awaiting", badge: "bg-status-awaiting-soft text-status-awaiting" },
  payment_check: { dot: "bg-status-check", badge: "bg-status-check-soft text-status-check" },
  approved: { dot: "bg-status-approved", badge: "bg-status-approved-soft text-status-approved" },
  cancelled: { dot: "bg-status-cancelled", badge: "bg-status-cancelled-soft text-status-cancelled" },
};
