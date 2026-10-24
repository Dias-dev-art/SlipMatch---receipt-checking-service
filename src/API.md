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
| GET | `/api/v1/business` | settings, incl. `shop_code`, `telegram_link` (`https://t.me/<bot>?start=<shop_code>`, `null` without `TELEGRAM_BOT_USERNAME`; shown with a QR code in Settings) and `payment_qr_url` (full URL or `null`) |
| PATCH | `/api/v1/business` | partial: `name`, `shop_code` (`^[a-z0-9][a-z0-9-]{2,31}$`, 409 if taken), `delivery_enabled`, `delivery_fee`, `pickup_enabled`, `payment_instructions`, `unique_amount_cents`, `payment_timeout_minutes` (1–120), `greeting` (`""`/`null` clears). 422 if both pickup and delivery end up off |
| POST | `/api/v1/business/payment-qr` | multipart `file`: PNG/JPEG/WebP ≤ 2 MB (415/413 otherwise); served publicly at `/media/...` |
`/api/v1/auth/me` returns the same business object.

Orders and conversations include `customer: {id, display_name, username, phone}`: the Telegram
name, the @username (without @, may be `null`) and the phone number the customer shared with
the bot's "Share phone number" button at checkout (digits with country code, e.g. `60123456789`).

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

The AI hands off complaints, refunds and angry customers. The dashboard's chat panel (opened from
the toast or the "chats need you" button) lists them, shows the history, sends the owner's reply
through the bot and gives the chat back to the AI.

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/conversations?needs_owner=true` | chats the AI handed off: `{id, customer, needs_owner, handoff_reason, handoff_at, ai_paused_until, last_customer_message_at, last_message, created_at}`; most recent first |
| GET | `/api/v1/conversations/{id}/messages` | history, oldest first (`?limit=`, default 100) |
| POST | `/api/v1/conversations/{id}/reply` | `{text}` (1–1000 chars): sent to the customer's Telegram as `👩‍🍳 <shop name>:\n<text>`, stored as `sender=owner`; clears `needs_owner` and pauses the AI in this chat for 15 minutes after the reply (`ai_paused_until`); the dashboard calls `resume-ai` when the owner closes the chat panel |
| POST | `/api/v1/conversations/{id}/resume-ai` | clear `needs_owner`, `handoff_reason`, `handoff_at` and `ai_paused_until` |

A handoff nobody acts on resumes by itself 24h after `handoff_at` (timer job).

## Realtime

`GET /api/v1/events` — SSE. Token via `?token=` query param (EventSource cannot set headers). Events: `order.created`, `order.updated`, `payment.check_requested`, `conversation.needs_owner`, with JSON `{order_id | conversation_id}`.

## Media (public)

`GET /media/<business_id>/<file>` serves uploaded payment QRs and downloaded customer screenshots
(bytes in the `media_files` table, 404 if unknown, cached as immutable). The DB stores the `/media/...` path; API responses use
`PUBLIC_BASE_URL + path`, so a new ngrok or hosting URL does not break old links. Telegram gets QR photos uploaded as bytes, not by link.

## Telegram webhook (public)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/telegram/webhook` | `X-Telegram-Bot-Api-Secret-Token` must equal `TELEGRAM_WEBHOOK_SECRET` (401 otherwise); return 200 fast, process in background |

Registered by the backend itself at startup (`setWebhook` with `PUBLIC_BASE_URL/telegram/webhook`,
the secret and `allowed_updates=["message"]`); skipped without a token, a secret or an https URL.

Handled: private-chat `message` updates. `/start <shop_code>` ties the chat to that shop and sends
the welcome; text, photo (largest size) or image document, location go through the pipeline;
voice/audio → "text only" reply. A `contact` (the "Share phone number" button) saves the phone,
only when `contact.user_id` is the sender's own id, then finishes the checkout by code. The
sender's `username` is stored. Edited messages, groups and bots are ignored. Each `update_id` is
processed once (`processed_webhooks`, key `tg:<update_id>`).

Bot API calls (`app/telegram/client.py`): `sendMessage` (with a `request_contact` reply keyboard
when asking for the phone, `remove_keyboard` after it), `sendPhoto` (multipart upload of the QR
bytes), `sendChatAction` ("typing"), `getFile` + file download, `setWebhook`. Failures (e.g. 403:
the customer blocked the bot) are logged, never raised.

## Dev only

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/dev/simulate` | `{chat_id, text, phone?}` (`chat_id`: 5–20 digits, stands in for a Telegram chat; `phone` defaults to `chat_id`, so the simulator skips the "Share phone number" step; auth required, uses owner's business); returns `{reply, order, sent, outcome}` — `sent` is everything that would go to Telegram, `outcome` is `reply`, `ignored`, `handoff`, `fallback`, `needs_owner`, `ai_paused` or `unsupported_type` |
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

Results written by code before a tool runs, or instead of it:

```json
{"error": "phone_needed", "note": "A button to share the phone number was sent. Ask the customer to tap it."}
{"error": "customer_not_done", "note": "The customer has not said they are finished. Ask if they want anything else."}
{"error": "customer_did_not_choose", "note": "The customer has not said pickup or delivery yet. Ask them."}
```

`request_payment` itself sends the QR image and reference message through Telegram. The LLM's final text should only add a short friendly line, not repeat the amount.
