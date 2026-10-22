# Backend — FastAPI

Read `../CLAUDE.md`, `../ARCHITECTURE.md`, `../DATABASE.md` and `../API.md` first.

## Stack

- Python 3.12, managed with `uv`
- FastAPI, Uvicorn
- SQLModel + Alembic, PostgreSQL via `psycopg`
- Pydantic v2 + `pydantic-settings` for config
- Auth: JWT with `pyjwt`, password hashing with `pwdlib` (argon2/bcrypt) — follow the auth pattern of the official Full Stack FastAPI Template (OAuth2PasswordBearer, `get_current_user` dependency, `SessionDep`, `CurrentUser` type aliases)
- `httpx` for WhatsApp Graph API calls
- `openai` SDK pointed at `LLM_BASE_URL` (OpenRouter now, vLLM later)
- `cryptography` (Fernet) to encrypt WhatsApp tokens
- Tests: `pytest`, `pytest-asyncio`; lint/format: `ruff`

## Structure

```
backend/
├── pyproject.toml
├── alembic/ + alembic.ini
└── app/
    ├── main.py              # app factory, CORS, routers, lifespan starts timer loop
    ├── core/
    │   ├── config.py        # Settings from env
    │   ├── db.py            # engine, get_session
    │   ├── security.py      # hashing, JWT create/verify, encrypt/decrypt tokens
    │   └── deps.py          # SessionDep, CurrentOwner, CurrentBusiness
    ├── models/              # SQLModel tables (one file per table group)
    ├── schemas/             # request/response models
    ├── api/v1/              # auth, business, menu, orders, conversations, events, dev
    ├── webhook/
    │   ├── router.py        # GET verify, POST receive (signature check, 200, background), dedupe
    │   └── parser.py        # Meta payload → ParsedMessage / OwnerEcho
    ├── agent/
    │   ├── llm.py           # get_llm_client(), chat() wrapper, retries
    │   ├── prompt.py        # build system prompt from business + menu + order
    │   ├── tools.py         # TOOLS schemas (must match src/API.md exactly)
    │   ├── executor.py      # execute_tool(): validation + DB updates, returns JSON
    │   └── loop.py          # run_agent(): tool loop, reply guard, text-tool recovery, fallback
    ├── services/
    │   ├── pipeline.py      # handle_incoming(): exclusions, gatekeeping, agent, send; owner echoes
    │   ├── orders.py        # state machine transitions (the ONLY place status changes)
    │   ├── whatsapp.py      # GraphClient (send_text, send_image, download_media), WhatsAppOutbox
    │   ├── outbox.py        # Outbox protocol; get_outbox(session, business_id) for owner/timer messages
    │   ├── notify.py        # fixed-template messages to a customer outside a reply
    │   ├── handoff.py       # resume AI, owner takeover pause, 24h auto-resume
    │   ├── media.py         # /media files (payment QR, screenshots), absolute URLs
    │   ├── templates.py     # fixed customer messages (confirmed, cancelled, not received)
    │   ├── events.py        # in-process pub/sub for SSE per business
    │   └── timers.py        # expire orders, auto-resume handoffs, forget old webhook ids
    ├── evals/llm_scenarios.py  # real conversations against the configured LLM, PASS/FAIL
    ├── seed.py
    └── tests/               # fake LLM (tests/fake_llm.py) + fake Graph API transport; no network
```

## Rules

- `services/orders.py` owns all status transitions. Each function checks the current status and raises a domain error that maps to HTTP 409. Use row locks (`with_for_update`) when transitioning.
- `agent/executor.py` never trusts LLM numbers. Prices from DB, totals from `Decimal`, `menu_item_id` is a slug looked up with `business_id`.
- The webhook handler must respond within ~1s. Do all work in `BackgroundTasks` (fine for hackathon; a queue later).
- `pipeline.handle_incoming()` is used by both `/webhook` and `/dev/simulate`, with a `send` function injected (real WhatsApp vs return value). This keeps the simulator honest.
- Log each agent turn (input, tool calls, tool results, reply) to `messages.payload` for debugging. Mask phone numbers in normal logs.
- Keep the system prompt in `prompt.py` short and explicit; include only available menu items.
- Every endpoint that touches tenant data uses `CurrentBusiness` and filters by its id.

## Commands

```bash
uv sync
docker compose up -d db              # from repo root
uv run alembic upgrade head
uv run python -m app.seed
uv run fastapi dev app/main.py       # http://localhost:8000/docs
uv run pytest
uv run ruff check . && uv run ruff format .
uv run python -m app.evals.llm_scenarios   # check the real LLM (uses LLM_* from .env)
ngrok http 8000                      # for Meta webhook in dev (see docs/WHATSAPP_SETUP.md)
```

## Tests that must exist

- Executor: add valid item, add unknown item → `not_on_menu`, sold-out item, totals with delivery fee, missing fields.
- State machine: every allowed transition, and 409 for disallowed ones; double approve is a no-op.
- Webhook: verify GET, bad signature → 401, duplicate message id processed once.
- Tenancy: owner A cannot read or approve owner B's orders.
- Agent loop with a fake LLM client that returns scripted tool calls (no network in tests).
