# Connect the Telegram bot

Goal: a customer opens the bot on their phone, writes "boss nak 2 nasi lemak tapau", and the AI
waiter answers. The owner approves the payment on the website, and the confirmation arrives in
Telegram.

One bot serves every shop. Each shop has a link `https://t.me/<bot>?start=<shop_code>`. Opening it
sends `/start <shop_code>`, which ties that chat to the shop. The demo shop's code is
`kak-ani-kitchen`.

## What you need at the end

| Value | Goes to |
| --- | --- |
| Bot token from @BotFather | `.env` → `TELEGRAM_BOT_TOKEN` |
| Bot username (without @) | `.env` → `TELEGRAM_BOT_USERNAME` |
| A secret you invent | `.env` → `TELEGRAM_WEBHOOK_SECRET` |
| Public HTTPS URL of the backend (ngrok) | `.env` → `PUBLIC_BASE_URL` |
| Optional: shop for chats opened without a link | `.env` → `TELEGRAM_DEFAULT_SHOP` |

Never commit `.env`.

## 1. Create the bot (1 minute)

1. In Telegram, open **@BotFather** → `/newbot`.
2. Name: e.g. `Waitly`. Username: must end in `bot`, e.g. `WaitlyBot`.
3. Copy the token (`123456789:AA...`) into `TELEGRAM_BOT_TOKEN`, and the username into
   `TELEGRAM_BOT_USERNAME`.
4. Make a secret (letters, digits, `_` and `-` only):
   `python -c "import secrets; print(secrets.token_urlsafe(32))"` → `TELEGRAM_WEBHOOK_SECRET`.

Optional polish in @BotFather: `/setuserpic` (shop logo), `/setdescription` ("Order from Kak Ani
Kitchen in 1 minute"), `/setcommands` → `start - Start a new order`.

## 2. Expose the backend

```bash
docker compose up -d db                       # repo root
cd src/backend && uv run alembic upgrade head
uv run python -m app.seed                     # prints the demo shop's Telegram link
ngrok http 8000                               # gives https://<something>.ngrok-free.app
```

Put the ngrok URL in `.env` as `PUBLIC_BASE_URL` (no trailing slash), then start the backend:

```bash
uv run fastapi dev app/main.py
```

At startup the backend registers the webhook with Telegram (`setWebhook`, with your secret). The log
shows:

```
INFO app.telegram.setup: Telegram webhook set: https://<something>.ngrok-free.app/telegram/webhook
INFO app.telegram.setup: Telegram link for Kak Ani Kitchen: https://t.me/WaitlyBot?start=kak-ani-kitchen
```

There is nothing to configure on Telegram's side. If the ngrok URL changes, update
`PUBLIC_BASE_URL` and restart.

On Replit, `PUBLIC_BASE_URL` is the published `https://<app>.replit.app`, and the same thing
happens on each start.

## 3. Owner setup (website)

Log in to the dashboard (demo: `demo@demo.my` / `demo1234`) and, in **Settings**, upload the
DuitNow QR and check the payment instructions. The bot sends the QR to the customer as a photo.

**Settings → Your Telegram ordering link** shows the shop's link with **Copy**, **Open in
Telegram** and a QR code (**Download QR** for printing). The shop code (end of the link) can be
changed there too.

## 4. Test

On your phone, open the shop link and press **Start**:

1. Welcome message: "You're ordering from <shop>" + the menu.
2. "hi, what's good here?" → a short recommendation from the menu.
3. "mee goreng pedas tak?" → an answer from the menu description.
4. "one nasi lemak" → "can I also add one mee goreng and 2 teh tarik" → every reply ends with
   the real cart and total, then "Pickup or delivery?".
5. "tapau" → "itu je" → the cart + a **📱 Share phone number** button → tap it → QR photo +
   "Pay RM…, reference X123".
6. Send the transfer screenshot + "dah bayar" → the dashboard plays a sound, card under
   **Check payment**, with the customer's name, @username and phone.
7. Press **Approve** on the website → "Payment received, thank you! Order X123 is confirmed..."
   arrives in Telegram.
8. "the food yesterday was cold, I want a refund" → the dashboard shows a toast → **Open chat** →
   reply → it arrives in Telegram as "👩‍🍳 <shop>: …" → close the chat panel → the AI answers the
   customer again.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No "Telegram webhook set" in the log | `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` set? `PUBLIC_BASE_URL` starts with `https://`? Restarted after editing `.env`? |
| Log: `Telegram setWebhook rejected 401` | the token is wrong: copy it again from @BotFather |
| Bot is silent, nothing in the backend log | ngrok running and the same URL as `PUBLIC_BASE_URL`? Open `https://api.telegram.org/bot<token>/getWebhookInfo` in a browser: `last_error_message` says why |
| `401 Bad secret token` in the log | `TELEGRAM_WEBHOOK_SECRET` changed after the webhook was set: restart, which registers it again |
| Bot answers "please open your shop's Telegram link" | the chat has no shop: open the link with `?start=<shop_code>`, or set `TELEGRAM_DEFAULT_SHOP` |
| Log: `Telegram sendMessage rejected 403` | the customer blocked the bot |
| AI is silent in one chat | the chat was handed to the owner: press **Resume AI** on the toast, or `POST /api/v1/conversations/{id}/resume-ai` |
| One bot token on two servers (laptop + Replit) | the last one to start wins the webhook. Use a second bot for local dev |
