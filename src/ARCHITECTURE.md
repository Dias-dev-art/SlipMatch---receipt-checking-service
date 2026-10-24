# Architecture

## Components

```
Customer (Telegram app)
      │  message to the shared bot
      ▼
Telegram Bot API ──POST /telegram/webhook──▶ FastAPI backend ◀──REST + SSE──▶ Owner dashboard (Next.js)
      ▲                                       │      │
      └──── POST api.telegram.org/bot…/send* ─┘      │
                                                     ├──▶ PostgreSQL (menus, orders, chats)
                                                     └──▶ LLM endpoint (OpenRouter → later vLLM on RunPod)
```

| Component | Responsibility |
| --- | --- |
| Telegram bot | One bot for every shop. Delivers customer messages to our webhook and sends our replies, QR photos and confirmations |
| FastAPI backend | Webhook, shop routing, agent loop, tool validation, order state machine, timers, REST API for the dashboard, SSE events |
| LLM | Talks to the customer like a waiter and chooses tool calls. Has no authority over data |
| PostgreSQL | Businesses, owners, menus, customers, conversations, messages, orders |
| Owner dashboard | Login, menu editor, live orders (customer name, @username, phone), approve/reject, settings with the shop's Telegram link + QR, chat panel for handed-off chats (reply through the bot, Resume AI). Every owner action happens here; the bot is only for customers |

## Shops and the shared bot

Each business has a `shop_code` (made from its name at registration, e.g. `kak-ani-kitchen`). Its
link is `https://t.me/<TELEGRAM_BOT_USERNAME>?start=<shop_code>` (`telegram_link` in
`GET /api/v1/business`), printed as a QR code at the counter. Opening it sends `/start <shop_code>`:

- the chat is tied to that shop (`telegram_chats`); opening another shop's link switches it;
- the bot sends a fixed welcome (`templates.welcome`, or the business `greeting`). No LLM call.

A chat that never opened a link goes to `TELEGRAM_DEFAULT_SHOP` (the demo shop), or gets a fixed
"please open your shop's link" reply.

## One message, end to end

1. Customer writes to the bot.
2. Telegram sends `POST /telegram/webhook` with an `Update` (`update_id`, `message.chat.id`,
   `message_id`, text / photo / location…).
3. Backend checks `X-Telegram-Bot-Api-Secret-Token` against `TELEGRAM_WEBHOOK_SECRET`, returns `200`
   immediately and processes in a background task. Telegram retries if we are slow, so never do
   LLM work before responding. Groups, edited messages and other bots are ignored.
4. **Idempotency**: if `tg:<update_id>` already exists in `processed_webhooks`, stop.
5. **Resolve tenant**: `chat_id` → `telegram_chats` → `business_id` (or the default shop).
   `/start` is handled here (see above) and never reaches the LLM.
6. Send "typing…" (`sendChatAction`) while the AI thinks.
7. **Gatekeeping** (any hit means the AI does not reply):
   - Conversation has `ai_paused_until > now()` (the owner replied from the dashboard).
   - Conversation is flagged `needs_owner`.
8. Find or create `customer` (Telegram chat id, name, @username) and the active `conversation`.
   Save the incoming message. A shared contact ("Share phone number" button) instead saves the
   phone and finishes the checkout by code (see "Phone at checkout").
9. Handle non-text types: `location` → store lat/lng as the address; `photo` (or an image sent as
   a file) → download with `getFile` and attach to the current order (payment screenshot);
   voice/other → polite reply asking for text.
10. Run the **agent loop** (below).
11. Send the final assistant text with `sendMessage`. Save it as a message.
12. Push an SSE event to the owner's dashboard if an order changed.

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

- The system prompt contains: business name, the menu as compact JSON (id, name, price, description, tags, available), current cart and order status, required fields still missing, the rules ("only use ids from the menu", "never state prices not in the menu", "complaints → handoff_to_owner") and **how to talk** (below).
- Only available menu items are included. When the owner toggles "sold out", the AI stops offering it immediately.
- Tool results are JSON. Errors are normal results the LLM must react to, e.g. `{"error":"not_on_menu","item":"palau","suggestions":["nasi_lemak"]}`.
- If the loop hits the iteration limit or the LLM errors, send a fixed fallback message and flag `needs_owner`.
- **Reply guard** (`agent/loop.py`): a text reply is never sent if it contains a tool name, JSON or chat-template tokens, or claims the payment is received/confirmed/paid (English and Malay). The model gets one correction; a second bad reply → fallback.
- **Text tool recovery**: if the whole reply is just `request_payment` or `mark_paid_by_customer` (small models do this), the backend runs that tool through the normal executor once per turn and lets the model reply to the result. Tool calls written as text (`<tool_call>{"name": "add_item", ...}`) are run the same way.
- **Code-decided steps** (`agent/intents.py`), run before the LLM is asked: the cart is complete and the customer says they are done ("itu je", "that's all", "nak bayar", "send the QR", or "no" after "anything else?") → `request_payment`; the order is awaiting payment and the customer says they paid ("dah bayar", "paid", a screenshot) → `mark_paid_by_customer`; they ask for the QR again → the payment details are sent again. The LLM then only adds a short line. Seen live: the model often chats instead of calling these.
- **Cart summary by code**: after a turn that changed the cart, the reply is the AI's short opener ("Boleh boss!") + the real cart (`templates.cart_summary`: items, delivery fee, total) + the next question from `missing_fields` ("Pickup or delivery?", "What's the delivery address?", "Anything else, or shall I send the payment details?"). The AI's own sentences about the cart are dropped. Seen live: right after a real tool call the model said "One Besh and one Mee Goreng are added" with only Besh in the cart.
- **Items by code** (`intents.parse_items`): when the model claims it added items but called no tool (seen live: "can I also add one mee goreng and 2 teh tarik" → no `add_item`, twice), code reads the menu items and quantities from the customer's message (names, fuzzy for typos, "2" / "dua" / "one" / "x2") and runs `add_item` for them. Only the customer's words count.
- **Tool gates** (`intents.premature_tool`): `set_order_type` only runs when the customer mentioned pickup/delivery (tapau, hantar, delivery…), `request_payment` only when they said they are done. Seen live: after "one nasi lemak" the model chose pickup and sent the QR by itself.
- **More steps code answers by itself** (`loop.run_agent`, before the model; seen live 2026-10-26 on a 1-item shop with delivery off):
  - "can you pass me to the owner" / "talk to a human" / "nak cakap dengan owner" → `handoff_to_owner` by code (the model wrote "Handing over…" and did not hand off);
  - "pickup" / "tapau" / "delivery" / "hantar" → `set_order_type` by code, or "Sorry, <shop> doesn't do delivery right now, only pickup." when that type is switched off in Settings (the model accepted delivery although it was off). A shop with only one type gets it set automatically and the customer is never asked; the welcome says "Pickup only." / "Delivery only (+RM3.00).";
  - "menu" / "what do you have" / "ada apa" → the real menu from the database, or "nothing is available" for an empty menu (the model invented Fries, Nuggets, Coke and Sprite for a 1-item menu). An empty menu is also stated in the prompt.
- Made-up promises like "Expected delivery time: 30-45 minutes" are dropped like status claims.
- **Claims without a tool**: a reply that says items were added, an address was saved, gives a total that is not the real cart total, or mentions the QR/reference, in a turn where no tool ran, is not sent. If the customer's words name menu items, code adds them (above); otherwise the model is asked again, and a second such reply becomes a fixed "which items would you like?" (the chat stays with the AI). Questions ("Shall I add one?") are not claims; line breaks end a sentence, so a copied "Your order: … Total: RM21.00" block is caught.
- **Dropped sentences**: sentences saying the order is confirmed, ready, on its way or paid, or showing internals (menu ids like `mee_goreng`), are removed from the reply; only the owner confirms an order.

### Phone at checkout

Telegram shares a phone number only when the customer taps a `request_contact` button. When
`request_payment` runs (by code or by the model) and the customer has no phone yet, the bot
sends the cart summary + "Almost done! Please tap the button below to share your phone number"
with a **📱 Share phone number** keyboard, and the turn ends (no QR yet). When the contact
arrives (only the customer's own: `contact.user_id == from.id`) the phone is stored, the keyboard
is removed, and code sends the QR + payment details without asking the LLM. The owner sees the
phone and @username on the order. `/dev/simulate` skips this step (`phone` defaults to the chat id).

### Owner replies

The dashboard's chat panel sends `POST /conversations/{id}/reply`: the text goes to the customer
through the bot as `👩‍🍳 <shop name>:` + text, is stored as `sender=owner`, clears `needs_owner` and
pauses the AI in that chat while the owner talks: 15 minutes after their last reply. Closing the
chat panel hands the chat back to the AI at once (`resume-ai`), and so does the customer's `/start`.
Seen live: with a 24h pause the customer was ignored after the owner had left.
- Keep the LLM client behind `get_llm_client()` so OpenRouter and the vLLM endpoint are interchangeable.
- `uv run python -m app.evals.llm_scenarios` runs real conversations against the configured model with PASS/FAIL checks.

### Waiter persona

The prompt only says "short, friendly, plain text" and "greetings and small talk: reply briefly, then ask what they would like to order". **Do not add tone or persona instructions.** Measured on the Qwen 7B endpoint (2026-10-25), "1 teh tarik" → `add_item`:

| Prompt | add_item |
| --- | --- |
| original rules | 8/8 |
| + "Sound like a friendly waiter: warm, casual…" | 0/6 |
| + "Every time the customer asks for food, call add_item…" (without the waiter line) | 4/6 |

With a persona line the model chats ("Sure thing! Adding a Teh Tarik…") instead of calling tools, so nothing reaches the cart and no QR is sent. Warmth has to come from fine-tuning data, not the prompt. Prices, totals, status changes and payment wording are decided by code either way.

`/start` begins a new conversation (unless a payment is pending or the owner has the chat), so the AI never sees an old chat it could copy.

The `/start` welcome is a template: "You're ordering from <shop>" plus the available menu with prices, so the customer knows which shop the shared bot is serving.

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
| `handoff_to_owner(reason)` | Complaints, refunds, angry customers. Flag conversation `needs_owner`, notify owner, AI stops replying |
| `ignore_or_flag(reason)` | Spam or abuse. Do not reply; optionally flag for owner |

The cart is locked once the order is `awaiting_payment`. If the customer wants changes after that, the backend cancels the payment request and returns to `chatting`.

## Payment verification (manual)

1. On `request_payment`: backend sends the business's DuitNow QR (uploaded by the owner in settings) as a Telegram photo, uploaded from the database, and the text "Pay RM10.00, reference A123".
2. Optional: make the amount unique (e.g. RM10.03) so the owner can find the transfer quickly. Configurable per business.
3. Customer says "paid" (and may send a screenshot) → `payment_check`.
4. Dashboard shows a card "Check payment: RM10.00, ref A123" with sound + countdown.
5. Owner checks the bank app and presses **Approve** or **Not received**.
6. Approve → `approved`, fixed confirmation template sent to the customer's Telegram chat.
7. Not received → back to `awaiting_payment`, customer told "we don't see the payment yet".
8. No action in 10 minutes → `cancelled`, customer informed. Owner can **Restore** if money arrives late.

Screenshots are shown to the owner as a hint only. The AI must never say "payment received".

## Timers

A background job runs every 30 seconds: select orders in `awaiting_payment` or `payment_check` where `expires_at < now()`, move them to `cancelled`, send the cancellation template, emit SSE. Use `SELECT ... FOR UPDATE SKIP LOCKED` so two workers never cancel the same order twice. For the hackathon an asyncio loop started in the FastAPI lifespan is enough. The same loop resumes handoffs older than 24h and forgets `processed_webhooks` rows older than 7 days.

Messages not triggered by a customer message (owner actions, timers) go through `get_outbox(session, business_id)`: the Telegram bot when `TELEGRAM_BOT_TOKEN` is set, otherwise only stored and logged.

At startup the same lifespan calls `setWebhook` (`PUBLIC_BASE_URL/telegram/webhook` + the secret) and logs every shop's link, so a new ngrok URL only needs a restart.

## Off-topic chats

Customers reach the bot through a shop's link, so nearly everyone who writes is a customer (there is no "never auto-reply" list: friends don't end up in a shop's bot by accident). Small talk gets a short reply that leads back to the menu; the LLM calls `ignore_or_flag` for spam or abuse.

## Handoff recovery

A chat flagged `needs_owner` (handoff or fallback) goes back to the AI when:
- the owner presses **Resume AI** in the chat panel (`POST /api/v1/conversations/{id}/resume-ai`), or
- the owner closes the chat panel after replying, or 15 minutes pass after their last reply, or
- the customer presses Start (`/start`) while the owner's pause is on, or
- nobody acted on it for 24h after `handoff_at` (timer job).

## Multi-tenancy

- One domain, one backend, one database, one bot. Every tenant table has `business_id`.
- Dashboard requests: `business_id` comes from the JWT's owner, never from the request body.
- Webhook requests: `business_id` comes from the chat's shop (`telegram_chats`, set by `/start <shop_code>`).
- The bot token is a server secret (`TELEGRAM_BOT_TOKEN`), never stored in the database.

## Realtime to dashboard

`GET /api/v1/events` (SSE, token in `?token=`) streams events for the owner's business: `order.created`, `order.updated`, `payment.check_requested`, `conversation.needs_owner`. The dashboard re-fetches on each event, plays a sound on `payment.check_requested`, and shows a "Resume AI" toast on `conversation.needs_owner`.

## Dev simulator

`POST /dev/simulate` (enabled when `ENV` is `dev` or `test`) takes `{chat_id, text}`, uses the logged-in owner's business, and runs exactly the same pipeline as the webhook, but returns what would be sent instead of sending it to Telegram. There is no Test chat page in the dashboard; call it from `/docs` or with curl. Build and test the agent with this before connecting the bot.
