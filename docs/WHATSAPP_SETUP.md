# Connect a WhatsApp test number

Goal: a real phone sends "boss nak 2 nasi lemak tapau" to the business number, and the AI answers.
The backend code is ready (`/webhook`, sending, media, owner echoes); this is the Meta setup.
Meta's screens change often. If a button below has moved, look for the same words in the
WhatsApp section of the app dashboard.

## What you need at the end

| Value | Goes to |
| --- | --- |
| App secret | `.env` → `WHATSAPP_APP_SECRET` |
| A verify token you invent (any random string) | `.env` → `WHATSAPP_VERIFY_TOKEN` |
| Phone number ID | dashboard Settings → WhatsApp number |
| Access token | dashboard Settings → WhatsApp number (stored encrypted) |
| Public HTTPS URL of the backend (ngrok) | `.env` → `PUBLIC_BASE_URL`, and the Meta webhook URL |

`TOKEN_ENCRYPTION_KEY` must also be set in `.env` (Fernet key; see `.env.example`). Never commit `.env`.

## 1. Meta app and test number

1. Go to developers.facebook.com → **My Apps** → **Create app** → type **Business**.
2. Add the **WhatsApp** product. Meta creates a test business account and a **test phone number**.
3. In **WhatsApp → API Setup**:
   - copy the **Phone number ID** (not the phone number itself);
   - under "To", add and verify your own phone number. A test number can only message
     numbers on this list (up to 5).
4. **App settings → Basic** → copy the **App secret**.

## 2. Access token

The temporary token on the API Setup page expires after ~24h. Fine for a first test; for the demo
make a permanent one:

1. business.facebook.com → **Business settings → Users → System users** → add one (Admin).
2. **Add assets** → your app → full control.
3. **Generate new token** → select the app → permissions `whatsapp_business_messaging` and
   `whatsapp_business_management` → copy the token.

## 3. Expose the backend

```bash
docker compose up -d db                       # repo root
cd src/backend && uv run alembic upgrade head
uv run fastapi dev app/main.py                # http://localhost:8000
ngrok http 8000                               # gives https://<something>.ngrok-free.app
```

Put the ngrok URL in `.env` as `PUBLIC_BASE_URL` (no trailing slash), plus
`WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN`, then restart the backend (`.env` is read at start).

## 4. Webhook

In the Meta app: **WhatsApp → Configuration → Webhook → Edit**:

- Callback URL: `https://<something>.ngrok-free.app/webhook`
- Verify token: the same string as `WHATSAPP_VERIFY_TOKEN`
- **Verify and save**. Meta calls `GET /webhook`; the backend answers with the challenge.
- **Webhook fields**: subscribe to `messages`. If the number also runs in the WhatsApp Business
  app (Coexistence), subscribe to `smb_message_echoes` too: then a manual reply by the owner
  pauses the AI in that chat for 24h.

## 5. Connect the number to the business

Log in to the dashboard (demo: `demo@demo.my` / `demo1234`) → **Settings → WhatsApp number**:
Phone number ID, display phone, access token → **Connect**. Or with the API:

```bash
curl -X PUT http://localhost:8000/api/v1/business/whatsapp \
  -H "Authorization: Bearer <jwt from /api/v1/auth/login>" -H "Content-Type: application/json" \
  -d '{"phone_number_id": "<id>", "display_phone": "+60 ...", "access_token": "<token>"}'
```

Also upload the DuitNow QR in **Settings → Payment**. WhatsApp fetches it from
`PUBLIC_BASE_URL/media/...`, so ngrok must be running.

## 6. Test

From your verified phone, message the test number:

1. "boss nak 2 nasi lemak tapau" → AI reply.
2. "itu je" → QR image + "Pay RM16.00, reference X123".
3. "dah bayar" (+ a screenshot) → the dashboard plays a sound, card under **Check payment**.
4. Press **Approve** → the confirmation arrives in WhatsApp.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Meta says the callback URL could not be verified | backend running? ngrok URL + `/webhook`? verify token equal in Meta and `.env`? backend restarted after editing `.env`? |
| Messages arrive (backend log) but nothing is sent | log line `WhatsApp send rejected`: 401 = token expired; `131030` = recipient not in the test number's allowed list; `131047` = more than 24h since the customer's last message |
| `401 Bad signature` in the backend log | `WHATSAPP_APP_SECRET` is not this app's secret |
| "Server is missing TOKEN_ENCRYPTION_KEY" when connecting | set it in `.env` and restart. Changing the key later makes saved tokens unreadable: connect the number again |
| QR image not delivered | `PUBLIC_BASE_URL` must be the public https URL, not localhost |
| AI is silent in one chat | the chat was handed to the owner or the owner replied by hand: press **Resume AI** on the toast or `POST /api/v1/conversations/{id}/resume-ai` |
