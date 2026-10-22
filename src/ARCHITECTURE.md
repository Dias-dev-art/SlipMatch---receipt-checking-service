# Architecture

## Components

```
Customer (WhatsApp)
      │  message
      ▼
Meta WhatsApp Cloud API ──POST /webhook──▶ FastAPI backend ◀──REST + SSE──▶ Owner dashboard (Next.js)
      ▲                                     │      │
      └────POST graph.facebook.com/messages─┘      │
                                                   ├──▶ PostgreSQL (menus, orders, chats)
                                                   └──▶ LLM endpoint (OpenRouter → later vLLM on RunPod)
```

| Component | Responsibility |
| --- | --- |
| WhatsApp Cloud API | Delivers customer messages to our webhook, sends our replies |
| FastAPI backend | Webhook, agent loop, tool validation, order state machine, timers, REST API for the dashboard, SSE events |
| LLM | Understands the customer and chooses tool calls. Has no authority over data |
| PostgreSQL | Businesses, owners, menus, customers, conversations, messages, orders |
| Owner dashboard | Login, menu editor, live orders, approve/reject, settings, "Resume AI" on handoff alerts (no inbox: the owner answers handed-off chats in the WhatsApp Business app) |

## One message, end to end

1. Customer sends a WhatsApp message to the business number.
2. Meta sends `POST /webhook` with JSON containing `phone_number_id` (the business number), `from` (customer), message `id`, `type` and content.
3. Backend verifies `X-Hub-Signature-256` with the app secret, returns `200` immediately and processes in a background task. Meta retries if we are slow, so never do LLM work before responding.
4. **Idempotency**: if the WhatsApp message `id` already exists in `processed_webhooks`, stop.
5. **Resolve tenant**: `phone_number_id` → `whatsapp_accounts` → `business_id`. Unknown number → log and stop.
6. **Gatekeeping** (in this order; any hit means the AI does not reply):
   - Customer phone is in this business's `contact_exclusions` (friends, family, suppliers).
   - Conversation has `ai_paused_until > now()` (owner replied manually, see "Owner takeover").
   - Conversation is flagged `needs_owner`.
7. Find or create `customer` and the active `conversation`. Save the incoming message.
8. Handle non-text types: `location` → store lat/lng as the address; `image` → download via media API and attach to the current order (payment screenshot); audio/other → polite reply asking for text.
9. Run the **agent loop** (below).
10. Send the final assistant text back with `POST https://graph.facebook.com/<version>/<phone_number_id>/messages`. Save it as a message.
11. Push an SSE event to the owner's dashboard if an order changed.

## Agent loop

```
messages = [system_prompt(business, menu, current_order)] + last N conversation messages
loop (max 6 iterations):
    resp = llm.chat.completions.create(model, messages, tools=TOOLS)
    if resp has tool_calls:
        for each call: result = execute_tool(call, business_id, conversation)   ← Python validates
        append assistant tool_calls + tool results to messages
        continue
    else:
        return resp.content  (the reply to send)
```

- The system prompt contains: business name, the menu as compact JSON (id, name, price, description, tags, available), current cart and order status, required fields still missing, and rules ("only use ids from the menu", "never state prices not in the menu", "if the menu does not answer, call handoff_to_owner", "reply in the customer's language, short and friendly").
- Only available menu items are included. When the owner toggles "sold out", the AI stops offering it immediately.
- Tool results are JSON. Errors are normal results the LLM must react to, e.g. `{"error":"not_on_menu","item":"palau","suggestions":["nasi_lemak"]}`.
- If the loop hits the iteration limit or the LLM errors, send a fixed fallback message and flag `needs_owner`.
- **Reply guard** (`agent/loop.py`): a text reply is never sent if it contains a tool name, JSON or chat-template tokens, or claims the payment is received/confirmed/paid (English and Malay). The model gets one correction; a second bad reply → fallback.
- **Text tool recovery**: if the whole reply is just `request_payment` or `mark_paid_by_customer` (small models do this), the backend runs that tool through the normal executor once per turn and lets the model reply to the result.
- Keep the LLM client behind `get_llm_client()` so OpenRouter and the vLLM endpoint are interchangeable.
- `uv run python -m app.evals.llm_scenarios` runs real conversations against the configured model with PASS/FAIL checks.

## Tools

Full schemas are in `API.md`. Summary:

| Tool | Backend does |
| --- | --- |
| `add_item(menu_item_id, qty, note?)` | Validate item belongs to business and is available; price from DB; recompute total |
| `remove_item(menu_item_id, qty?)` | Update cart; recompute total |
| `set_order_type(type)` | `pickup` or `delivery`; delivery adds the business delivery fee |
| `set_address(address)` | Store text address (location messages are stored by code, not by the LLM) |
| `request_payment()` | Check required fields; if complete → `awaiting_payment`, freeze amount, set `expires_at = now + 10 min`, send payment QR image + reference |
| `mark_paid_by_customer()` | `awaiting_payment` → `payment_check`, restart 10-min timer, notify owner |
| `handoff_to_owner(reason)` | Flag conversation `needs_owner`, notify owner, AI stops replying |
| `ignore_or_flag(reason)` | Not an order (friend, spam). Do not reply; optionally flag for owner |

The cart is locked once the order is `awaiting_payment`. If the customer wants changes after that, the backend cancels the payment request and returns to `chatting`.

## Payment verification (manual)

1. On `request_payment`: backend sends the business's DuitNow QR image (uploaded by the owner in settings) and the text "Pay RM10.00, reference A123".
2. Optional: make the amount unique (e.g. RM10.03) so the owner can find the transfer quickly. Configurable per business.
3. Customer says "paid" (and may send a screenshot) → `payment_check`.
4. Dashboard shows a card "Check payment: RM10.00, ref A123" with sound + countdown.
5. Owner checks the bank app and presses **Approve** or **Not received**.
6. Approve → `approved`, fixed confirmation template sent to the customer.
7. Not received → back to `awaiting_payment`, customer told "we don't see the payment yet".
8. No action in 10 minutes → `cancelled`, customer informed. Owner can **Restore** if money arrives late.

Screenshots are shown to the owner as a hint only. The AI must never say "payment received".

## Timers

A background job runs every 30 seconds: select orders in `awaiting_payment` or `payment_check` where `expires_at < now()`, move them to `cancelled`, send the cancellation template, emit SSE. Use `SELECT ... FOR UPDATE SKIP LOCKED` so two workers never cancel the same order twice. For the hackathon an asyncio loop started in the FastAPI lifespan is enough. The same loop resumes handoffs older than 24h and forgets `processed_webhooks` rows older than 7 days.

Messages not triggered by a customer message (owner actions, timers) go through `get_outbox(session, business_id)`: WhatsApp when the business has connected a number, otherwise only stored and logged.

## Friend vs customer

Default assumption: everyone who writes to a business number is a customer. Extra protection:

1. **Dedicated business number** (recommended): only customers write to it.
2. **Exclusion list**: owner marks numbers "never auto-reply" in settings. Messages from them are not stored and never reach the LLM.
3. **Owner takeover**: with WhatsApp Coexistence, messages the owner sends from the WhatsApp Business app arrive as `smb_message_echoes` events. When the owner replies manually in a chat, the message is stored (`sender=owner`), `needs_owner` is cleared and `ai_paused_until = now + 24h`.
4. **Intent check**: the LLM calls `ignore_or_flag` for non-order chats.

## Handoff recovery

A chat flagged `needs_owner` (handoff or fallback) goes back to the AI when:
- the owner presses **Resume AI** (dashboard toast on `conversation.needs_owner`, `POST /api/v1/conversations/{id}/resume-ai`), or
- the owner replies from the WhatsApp Business app (24h pause, then the AI answers again), or
- nobody acted on it for 24h after `handoff_at` (timer job).

## Multi-tenancy

- One domain, one backend, one database. Every tenant table has `business_id`.
- Dashboard requests: `business_id` comes from the JWT's owner, never from the request body.
- Webhook requests: `business_id` comes from `phone_number_id`.
- WhatsApp access tokens per business are stored encrypted.

## WhatsApp rules to respect

- Free-form messages only within 24 hours of the customer's last message. Outside that window, use pre-approved templates (needed if the owner approves very late).
- Meta's policy allows AI for a business's own customer service, not general-purpose assistants. Keep the agent on-topic.

## Realtime to dashboard

`GET /api/v1/events` (SSE, token in `?token=`) streams events for the owner's business: `order.created`, `order.updated`, `payment.check_requested`, `conversation.needs_owner`. The dashboard re-fetches on each event, plays a sound on `payment.check_requested`, and shows a "Resume AI" toast on `conversation.needs_owner`.

## Dev simulator

`POST /dev/simulate` (enabled when `ENV` is `dev` or `test`) takes `{customer_phone, text}`, uses the logged-in owner's business, and runs exactly the same pipeline as the webhook, but returns what would be sent instead of sending it to WhatsApp. There is no Test chat page in the dashboard; call it from `/docs` or with curl. Build and test the agent with this before connecting WhatsApp.
