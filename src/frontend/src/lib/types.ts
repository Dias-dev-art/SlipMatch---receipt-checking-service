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

export interface Customer {
  id: string;
  wa_phone: string;
  display_name: string | null;
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

export interface WhatsAppAccount {
  phone_number_id: string;
  display_phone: string;
  coexistence: boolean;
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
  whatsapp: WhatsAppAccount | null;
}

export type BusinessPatch = Partial<
  Pick<
    Business,
    | "name"
    | "delivery_enabled"
    | "delivery_fee"
    | "pickup_enabled"
    | "payment_instructions"
    | "unique_amount_cents"
    | "payment_timeout_minutes"
    | "greeting"
  >
>;

export interface WhatsAppInput {
  phone_number_id: string;
  display_phone: string;
  access_token: string;
}

export interface Exclusion {
  id: string;
  wa_phone: string;
  label: string;
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
