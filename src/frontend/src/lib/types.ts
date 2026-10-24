// Hand-written API shapes mirroring src/DATABASE.md and src/API.md.
// Replace with the generated `api-types.ts` (npm run gen:api) once the backend exists.
// Money fields are decimal strings ("10.00") exactly as the API returns them: display only, never compute.

export type Money = string;

export type OrderStatus =
  | "chatting"
  | "awaiting_payment"
  | "payment_check"
  | "approved"
  | "cancelled";

export type OrderType = "pickup" | "delivery";

export type CancelReason =
  | "payment_timeout"
  | "owner_timeout"
  | "owner_rejected"
  | "customer";

/** A Telegram customer. `phone` is shared with Telegram's button at checkout (digits, 60…). */
export interface Customer {
  id: string;
  display_name: string | null;
  /** Telegram @username without the @; not every Telegram user has one. */
  username: string | null;
  phone: string | null;
}

/** Name and price are the snapshot taken when the item was ordered. */
export interface OrderItem {
  id: string;
  menu_item_id: string;
  slug: string;
  name: string;
  unit_price: Money;
  qty: number;
  note: string | null;
}

export interface Order {
  id: string;
  conversation_id: string;
  customer: Customer;
  code: string;
  status: OrderStatus;
  order_type: OrderType | null;
  address_text: string | null;
  /** Decimal strings, like money. */
  location_lat: string | null;
  location_lng: string | null;
  items: OrderItem[];
  subtotal: Money;
  delivery_fee: Money;
  total: Money;
  payment_proof_media_url: string | null;
  expires_at: string | null;
  approved_at: string | null;
  cancelled_reason: CancelReason | null;
  created_at: string;
  updated_at: string;
}

export interface MenuItem {
  id: string;
  slug: string;
  name: string;
  price: Money;
  description: string;
  tags: string[];
  category: string | null;
  is_available: boolean;
  sort_order: number;
}

export interface MenuItemInput {
  name: string;
  price: Money;
  description: string;
  tags: string[];
  category: string | null;
  is_available: boolean;
}

export interface Business {
  id: string;
  name: string;
  delivery_enabled: boolean;
  delivery_fee: Money;
  pickup_enabled: boolean;
  payment_qr_url: string | null;
  payment_instructions: string;
  unique_amount_cents: boolean;
  payment_timeout_minutes: number;
  greeting: string | null;
  /** End of the Telegram link: t.me/<bot>?start=<shop_code>. */
  shop_code: string;
  /** The link customers open to order; null until the server knows the bot's username. */
  telegram_link: string | null;
}

export type BusinessPatch = Partial<
  Pick<
    Business,
    | "name"
    | "shop_code"
    | "delivery_enabled"
    | "delivery_fee"
    | "pickup_enabled"
    | "payment_instructions"
    | "unique_amount_cents"
    | "payment_timeout_minutes"
    | "greeting"
  >
>;

export type MessageSender = "customer" | "ai" | "owner" | "system";

export interface ConversationMessage {
  id: string;
  direction: "in" | "out";
  sender: MessageSender;
  type: "text" | "image" | "location" | "audio" | "other";
  body: string | null;
  created_at: string;
}

/** A customer chat; `needs_owner` = the AI handed it to the owner. */
export interface Conversation {
  id: string;
  customer: Customer;
  needs_owner: boolean;
  handoff_reason: string | null;
  handoff_at: string | null;
  ai_paused_until: string | null;
  last_customer_message_at: string;
  last_message: string | null;
  created_at: string;
}

export interface Owner {
  id: string;
  email: string;
  full_name: string;
}

export interface Me {
  owner: Owner;
  business: Business;
}

export type ServerEvent =
  | { type: "order.created"; order_id: string }
  | { type: "order.updated"; order_id: string }
  | { type: "payment.check_requested"; order_id: string }
  | { type: "conversation.needs_owner"; conversation_id: string };
