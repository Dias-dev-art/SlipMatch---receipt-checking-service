# API

Base URL: `NEXT_PUBLIC_API_URL` (dev `http://localhost:8000`). All dashboard endpoints are under `/api/v1` and need `Authorization: Bearer <jwt>`. The business is always taken from the token's owner.

## Auth

| Method | Path | Body | Returns |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | `{email, password, full_name, business_name}` | owner + business |
| POST | `/api/v1/auth/login` | form `username`, `password` (OAuth2 password flow) | `{access_token, token_type}` |
| GET | `/api/v1/auth/me` | | owner + business |

## Business settings

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/business` | settings |
| PATCH | `/api/v1/business` | delivery fee, pickup/delivery toggles, payment instructions, timeout, greeting |
| POST | `/api/v1/business/payment-qr` | multipart image upload |
| GET/POST/DELETE | `/api/v1/business/exclusions` | contact exclusion list |
| PUT | `/api/v1/business/whatsapp` | `{phone_number_id, display_phone, access_token}`; token stored encrypted |

## Menu

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/menu` | list |
| POST | `/api/v1/menu` | `{name, price, description, tags[], category?, is_available}`; slug generated |
| PATCH | `/api/v1/menu/{id}` | partial update |
| PATCH | `/api/v1/menu/{id}/availability` | `{is_available}` quick sold-out toggle |
| DELETE | `/api/v1/menu/{id}` | soft delete if referenced by orders |

## Orders

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/orders?status=` | list, newest first, with items |
| GET | `/api/v1/orders/{id}` | detail |
| POST | `/api/v1/orders/{id}/approve` | only from `payment_check`; sends confirmation template |
| POST | `/api/v1/orders/{id}/not-received` | `payment_check` → `awaiting_payment`, customer notified |
| POST | `/api/v1/orders/{id}/restore` | `cancelled` → `payment_check` |
| POST | `/api/v1/orders/{id}/cancel` | owner cancels with reason |

Invalid transitions return `409 Conflict`. Repeated clicks are safe.

## Handoff inbox

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/conversations?needs_owner=true` | chats the AI handed off |
| GET | `/api/v1/conversations/{id}/messages` | history |
| POST | `/api/v1/conversations/{id}/reply` | owner sends a manual message; pauses AI 24h |
| POST | `/api/v1/conversations/{id}/resume-ai` | clear `needs_owner` and pause |

## Realtime

`GET /api/v1/events` — SSE. Token via `?token=` query param (EventSource cannot set headers). Events: `order.created`, `order.updated`, `payment.check_requested`, `conversation.needs_owner`, with JSON `{order_id | conversation_id}`.

## WhatsApp webhook (public)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/webhook` | verification: if `hub.mode=subscribe` and `hub.verify_token` matches, return `hub.challenge` as plain text |
| POST | `/webhook` | verify `X-Hub-Signature-256`, return 200 fast, process in background |

## Dev only

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/dev/simulate` | `{customer_phone, text}` (auth required, uses owner's business); returns `{reply, order}` |
| POST | `/dev/reset` | wipe conversations/orders for the business |

## AI tools (shared with the ML dataset — do not rename)

OpenAI tools format. The LLM never sees `business_id` or `order_id`: the backend binds them from the conversation.

```json
[
  {"type":"function","function":{"name":"add_item","description":"Add a menu item to the cart. Use only ids from the provided menu.","parameters":{"type":"object","properties":{"menu_item_id":{"type":"string","description":"slug from the menu"},"qty":{"type":"integer","minimum":1},"note":{"type":"string"}},"required":["menu_item_id","qty"]}}},
  {"type":"function","function":{"name":"remove_item","description":"Remove a menu item from the cart, or reduce its quantity.","parameters":{"type":"object","properties":{"menu_item_id":{"type":"string"},"qty":{"type":"integer","minimum":1,"description":"omit to remove completely"}},"required":["menu_item_id"]}}},
  {"type":"function","function":{"name":"set_order_type","description":"Set pickup or delivery.","parameters":{"type":"object","properties":{"type":{"type":"string","enum":["pickup","delivery"]}},"required":["type"]}}},
  {"type":"function","function":{"name":"set_address","description":"Save the delivery address the customer typed.","parameters":{"type":"object","properties":{"address":{"type":"string"}},"required":["address"]}}},
  {"type":"function","function":{"name":"request_payment","description":"Call when the customer has finished choosing. Backend checks the order is complete and sends payment instructions.","parameters":{"type":"object","properties":{}}}},
  {"type":"function","function":{"name":"mark_paid_by_customer","description":"Call when the customer says they have paid. Does NOT confirm payment.","parameters":{"type":"object","properties":{}}}},
  {"type":"function","function":{"name":"handoff_to_owner","description":"Complaint, angry customer, or a question the menu cannot answer.","parameters":{"type":"object","properties":{"reason":{"type":"string"}},"required":["reason"]}}},
  {"type":"function","function":{"name":"ignore_or_flag","description":"Message is not about ordering (friend, spam, personal chat). No reply is sent.","parameters":{"type":"object","properties":{"reason":{"type":"string"}},"required":["reason"]}}}
]
```

### Tool results (examples)

```json
{"ok": true, "cart": [{"id":"mee_goreng","name":"Mee Goreng","qty":1,"unit_price":7.00}], "subtotal": 7.00, "total": 7.00, "missing_fields": ["order_type"]}
{"error": "not_on_menu", "item": "palau", "suggestions": ["nasi_lemak"]}
{"error": "sold_out", "item": "mee_goreng"}
{"error": "missing_fields", "fields": ["address"]}
{"ok": true, "status": "awaiting_payment", "code": "A123", "total": 10.00, "payment_sent": true}
```

`request_payment` itself sends the QR image and reference message through WhatsApp. The LLM's final text should only add a short friendly line, not repeat the amount.
