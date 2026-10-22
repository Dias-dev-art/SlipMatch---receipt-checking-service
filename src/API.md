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
| GET | `/api/v1/business` | settings, incl. `whatsapp: {phone_number_id, display_phone, coexistence} \| null` (never the token) and `payment_qr_url` (full URL or `null`) |
| PATCH | `/api/v1/business` | partial: `name`, `delivery_enabled`, `delivery_fee`, `pickup_enabled`, `payment_instructions`, `unique_amount_cents`, `payment_timeout_minutes` (1–120), `greeting` (`""`/`null` clears). 422 if both pickup and delivery end up off |
| POST | `/api/v1/business/payment-qr` | multipart `file`: PNG/JPEG/WebP ≤ 2 MB (415/413 otherwise); served publicly at `/media/...` |
| GET | `/api/v1/business/exclusions` | contact exclusion list `[{id, wa_phone, label}]` |
| POST | `/api/v1/business/exclusions` | `{wa_phone, label?}`; phone normalised to digits; 409 if already excluded |
| DELETE | `/api/v1/business/exclusions/{id}` | |
| PUT | `/api/v1/business/whatsapp` | `{phone_number_id, display_phone, access_token, coexistence?}`; token stored encrypted (503 without `TOKEN_ENCRYPTION_KEY`); 409 if the number belongs to another business |

`/api/v1/auth/me` returns the same business object.

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

## Handoff

There is no inbox page: the owner answers handed-off chats from the WhatsApp Business app (that
echo pauses the AI for 24h). These endpoints list them and give a chat back to the AI.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/conversations?needs_owner=true` | chats the AI handed off: `{id, customer, needs_owner, handoff_reason, handoff_at, ai_paused_until, last_customer_message_at, last_message, created_at}`; most recent first |
| GET | `/api/v1/conversations/{id}/messages` | history, oldest first (`?limit=`, default 100) |
| POST | `/api/v1/conversations/{id}/resume-ai` | clear `needs_owner`, `handoff_reason`, `handoff_at` and `ai_paused_until` |

A handoff nobody acts on resumes by itself 24h after `handoff_at` (timer job).

## Realtime

`GET /api/v1/events` — SSE. Token via `?token=` query param (EventSource cannot set headers). Events: `order.created`, `order.updated`, `payment.check_requested`, `conversation.needs_owner`, with JSON `{order_id | conversation_id}`.

## Media (public)

`GET /media/<business_id>/<file>` serves uploaded payment QRs and downloaded customer screenshots.
The DB stores the `/media/...` path; API responses and WhatsApp messages use
`PUBLIC_BASE_URL + path`, so a new ngrok or hosting URL does not break old links.

## WhatsApp webhook (public)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/webhook` | verification: if `hub.mode=subscribe` and `hub.verify_token` matches `WHATSAPP_VERIFY_TOKEN`, return `hub.challenge` as plain text; else 403 |
| POST | `/webhook` | verify `X-Hub-Signature-256` with `WHATSAPP_APP_SECRET` (401 if wrong or missing), return 200 fast, process in background |

Handled change fields: `messages` (text, interactive/button replies as text, location, image, audio → "text only" reply) and `smb_message_echoes` (owner typed in the WhatsApp Business app → AI paused 24h for that chat). Delivery `statuses` are ignored. Each message id is processed once (`processed_webhooks`).

## Dev only

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/dev/simulate` | `{customer_phone, text}` (auth required, uses owner's business); returns `{reply, order, sent, outcome}` — `sent` is everything that would go to WhatsApp, `outcome` is `reply`, `ignored`, `handoff`, `fallback`, `needs_owner`, `ai_paused`, `excluded` or `unsupported_type` |
| POST | `/dev/reset` | wipe conversations/orders for the business |

Enabled when `ENV` is `dev` or `test`.

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
