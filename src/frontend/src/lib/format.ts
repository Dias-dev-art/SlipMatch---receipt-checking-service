import type { Money } from "@/lib/types";

const myr = new Intl.NumberFormat("en-MY", { style: "currency", currency: "MYR" });

/** Formats an API money value ("10.00") as "RM 10.00". Display only. */
export function formatMYR(value: Money | number): string {
  // Intl gives "RM 10.00" with a no-break space; normalise to a regular space.
  return myr.format(Number(value)).replace(/ /g, " ");
}

const timeFormat = new Intl.DateTimeFormat("en-MY", { hour: "numeric", minute: "2-digit" });

export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso));
}

const dateTimeFormat = new Intl.DateTimeFormat("en-MY", {
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
});

export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "short" });

export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return "just now";
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), "hour");
  return relative.format(Math.round(seconds / 86400), "day");
}

/** "60123456789" → "+60 12-345 6789" */
export function formatPhone(phone: string): string {
  const m = phone.match(/^60(1\d)(\d{3,4})(\d{4})$/);
  if (!m) return `+${phone}`;
  return `+60 ${m[1]}-${m[2]} ${m[3]}`;
}

type CustomerLike = { display_name: string | null; username: string | null; phone: string | null };

/** Telegram name, else @username, else phone. */
export function customerName(customer: CustomerLike): string {
  if (customer.display_name) return customer.display_name;
  if (customer.username) return `@${customer.username}`;
  return customer.phone ? formatPhone(customer.phone) : "Customer";
}

/** "@username" when the customer has one, for a second line under the name. */
export function customerHandle(customer: CustomerLike): string | null {
  return customer.display_name && customer.username ? `@${customer.username}` : null;
}

export function telegramProfileUrl(username: string): string {
  return `https://t.me/${username}`;
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}
