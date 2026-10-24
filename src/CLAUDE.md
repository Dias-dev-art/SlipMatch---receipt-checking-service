# CLAUDE.md — WhatsApp AI Order Agent (start here)

Read this file first. Then read the doc for the area you are working on (paths are relative to `src/`):

| Area                                          | File                  |
| --------------------------------------------- | --------------------- |
| System design, message flow, AI agent loop    | `ARCHITECTURE.md`     |
| Database tables and relations                 | `DATABASE.md`         |
| HTTP endpoints and AI tool contracts          | `API.md`              |
| Backend conventions (FastAPI)                 | `backend/CLAUDE.md`   |
| Frontend conventions (Next.js)                | `frontend/CLAUDE.md`  |
| Fine-tuning + serving on RunPod (ML teammate) | `../runpod/CLAUDE.md` |

## What we are building

A SaaS for small food businesses in Malaysia. Customers order through the business's WhatsApp number. An AI agent handles the entire chat: answers menu questions, builds the order, checks it against the menu, asks for delivery details and sends payment instructions. The owner never reads the chats. The owner only opens a web dashboard, checks the bank for the payment and presses **Approve** or **Not received**.

### Goals

1. Owner does one action per order: verify payment in the bank and approve.
2. AI never invents menu items, prices or totals. The backend validates everything.
3. Multi-tenant from day one: many businesses, each with its own WhatsApp number, menu and settings.
4. Works with Manglish, typos and mixed languages ("boss nak 2 nasi lemak tapau").
5. Hackathon demo must work end to end on a real WhatsApp test number.

### Non-goals (for now)

- Payment gateway integration. Owner verifies payments manually in the bank.
- Courier integration, inventory, analytics, mobile app.
- General-purpose chatbot. Meta's WhatsApp Business policy forbids it; the agent only handles this business's orders.

## Core principle

**AI talks, code decides.**

- The LLM only chats and calls tools (`add_item`, `request_payment`, ...).
- Python validates every tool call against the database: item exists, belongs to this business, is available, price comes from the DB.
- Totals are always computed in Python. Never trust a number written by the LLM.
- Order status changes only happen in backend code, never because the LLM said so.
- Confirmation and cancellation messages to customers are fixed templates, not LLM output.

## Order status machine

```
chatting ──(cart + order type + address complete, request_payment)──▶ awaiting_payment
awaiting_payment ──(customer says "paid")──▶ payment_check
awaiting_payment ──(customer changes the cart)──▶ chatting (payment request cancelled)
awaiting_payment ──(10 min timeout)──▶ cancelled
payment_check ──(owner: Approve)──▶ approved
payment_check ──(owner: Not received)──▶ awaiting_payment (customer is told, timer restarts)
payment_check ──(10 min, owner did nothing)──▶ cancelled
cancelled ──(owner: Restore, money arrived late)──▶ payment_check
chatting | awaiting_payment | payment_check ──(owner: Cancel)──▶ cancelled
```

Any conversation can be flagged `needs_owner` (handoff) at any time. While flagged, the AI does not reply. It answers again after **Resume AI** on the dashboard, 24h after the owner's last manual reply, or 24h after the handoff if nobody acted.

## Monorepo layout

```
<repo root>/
├── docker-compose.yml     ← postgres (+ backend, frontend later)
├── .env.example
├── docs/                  ← screenshots, diagrams (empty for now)
├── runpod/                ← fine-tuning, serving and handler.py (GPU workload)
│   └── CLAUDE.md
├── src/
│   ├── CLAUDE.md          ← this file
│   ├── ARCHITECTURE.md
│   ├── DATABASE.md
│   ├── API.md
│   ├── backend/           ← FastAPI (Python)
│   │   └── CLAUDE.md
│   └── frontend/          ← Next.js (React + TypeScript) + shadcn/ui
│       └── CLAUDE.md
├── submission/            ← hackathon submission + proof of use PDFs
└── test/
```

## Tech stack

| Layer                 | Choice                                                                                                            |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| Frontend              | Next.js (App Router), React, TypeScript, Tailwind, shadcn/ui                                                      |
| Backend               | FastAPI, Python 3.12, Pydantic v2, SQLModel, Alembic                                                              |
| Auth                  | JWT (OAuth2 password flow) in FastAPI, same pattern as the official Full Stack FastAPI Template; passwords hashed |
| Database              | PostgreSQL 16 (local via Docker; can be hosted on Supabase or any managed Postgres)                               |
| Realtime to dashboard | Server-Sent Events (SSE) from FastAPI                                                                             |
| WhatsApp              | Meta WhatsApp Cloud API (webhooks in, Graph API out)                                                              |
| LLM (phase 1)         | OpenRouter via the OpenAI-compatible SDK                                                                          |
| LLM (phase 2)         | Our fine-tuned open-source model served by vLLM on RunPod (OpenAI-compatible)                                     |
| Local tunnel          | ngrok, so Meta can reach the local webhook                                                                        |

Switching LLMs must be a config change only: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Never call a provider SDK directly from business logic.

## Build order (do it in this order)

1. **Skeleton**: docker-compose with Postgres, FastAPI app with health check, Next.js app with shadcn installed.
2. **Auth + tenancy**: register/login, owner → business, every query scoped by `business_id`.
3. **Menu CRUD** in backend and dashboard.
4. **Agent loop with a dev simulator** (`POST /dev/simulate`), no WhatsApp yet. Get the full order flow working in a chat box on the dashboard.
5. **Orders dashboard**: live list via SSE, Approve / Not received / Restore buttons, 10-minute timers.
6. **WhatsApp**: webhook verify + receive, send text and image, idempotency.
7. **Friend detection**: exclusion list, owner-takeover pause, `ignore_or_flag`.
8. **Swap LLM** to the fine-tuned model endpoint when the ML track is ready.

Each step must work and be tested before the next one.

## Environment variables (`.env.example`)

```
ENV=dev                            # enables /dev/simulate
DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/orderagent
JWT_SECRET=change-me
JWT_EXPIRE_MINUTES=10080
FRONTEND_URL=http://localhost:3000
PUBLIC_BASE_URL=http://localhost:8000   # how Meta reaches the backend (ngrok URL in dev); /media links

LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-...
LLM_MODEL=<model id on OpenRouter with tool calling support>

WHATSAPP_VERIFY_TOKEN=any-random-string
WHATSAPP_APP_SECRET=...            # to verify X-Hub-Signature-256
WHATSAPP_GRAPH_VERSION=v21.0       # check the current version in Meta docs
TOKEN_ENCRYPTION_KEY=...           # Fernet key, encrypts per-business WhatsApp tokens in DB
                                   # uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

NEXT_PUBLIC_API_URL=http://localhost:8000
```

Never commit `.env`. Never log tokens, API keys or full customer phone numbers.

## Rules for Claude Code in this repo

- Keep the docs in `src/` (`ARCHITECTURE.md`, `DATABASE.md`, `API.md`) as the source of truth. If you change an endpoint, table or tool, update the doc in the same change.
- Tool names and JSON schemas in `API.md` are shared with the ML training dataset. Do not rename tools or parameters without telling the user.
- Every DB query on tenant data filters by `business_id` from the authenticated owner or from the resolved WhatsApp number.
- Prefer small, working increments. Run tests and linters before saying something is done.
- Ask before adding a new external service or paid dependency.
