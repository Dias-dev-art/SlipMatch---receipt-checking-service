# Project Name

> A one-sentence description of what your project does and who it is for.

---

## Team Information

| Field                 | Details                                                                                                                      |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| **Team Name**         | Quintuplets                                                                                                                  |
| **Team Domain**       | Domain 2                                                                                                                     |
| **SDG Track 8**       | SDG 8 - Promote sustained, inclusive and sustainable economic growth, full and productive employment and decent work for all |
| **Team Leader**       | Dias Zhumadilda                                                                                                              |
| **University**        | Xiamen University Malaysia                                                                                                   |
| **Number of Members** | 5                                                                                                                            |

## Links

| Resource          | Link                                           |
| ----------------- | ---------------------------------------------- |
| GitHub Repository | https://github.com/your-username/your-project  |
| Replit Project    | https://replit.com/@your-username/your-project |
| Live Demo         | https://your-project.replit.app                |
| RunPod Endpoint   | https://api.runpod.ai/v2/your-endpoint-id      |
| Slide Deck        | https://example.com/slides                     |
| Demo Video        | https://example.com/demo-video                 |

---

## Overview

### Problem

Small food businesses in Malaysia (home cooks, small kitchens, caterers) take most of their orders through chat. The owner has to answer every message by hand: menu questions, "ada pedas tak?", quantities, pickup or delivery, the address, the total and the payment details. Customers write in Malay, English, Manglish and typos, often while the owner is busy cooking. Orders get missed, totals are calculated by hand, and the owner still has to check each transfer against the right order in the bank app. These businesses have no staff for this and no payment-gateway integration.

### Solution

**Waitly** lets customers order from a shop by chatting with a Telegram bot, while the owner only checks the payment. One shared bot (@WaitlyAppBot) serves every shop: each business gets its own link (`t.me/WaitlyAppBot?start=<shop_code>`) to share or print as a QR code, and the bot welcomes the customer with that shop's name and menu.

An AI agent (Qwen2.5-7B-Instruct served on a RunPod endpoint) handles the chat: it answers menu questions, understands Manglish ("boss nak 2 nasi lemak tapau"), builds the order and asks for what is missing. The core rule is **"AI talks, code decides"**: the AI can only change an order through tool calls, and the backend checks every call against the database. Items must exist and be available, prices come from the menu, totals are calculated in Python and order status changes only happen in code. When the order is complete, the bot sends the shop's DuitNow QR with the amount and a reference code. The owner sees the order live on the Waitly web dashboard, checks the bank and presses **Approve** or **Not received**, and the customer gets a fixed confirmation message in Telegram. The AI never says a payment was received.

### Key Features

- **Telegram ordering bot** — One bot for every shop. Each shop has its own link and QR code, and the welcome message shows the shop's name and menu.
- **AI order agent** — Understands Malay, English and Manglish, answers questions from the menu and builds the order through validated tool calls.
- **Code-checked orders** — Prices, totals and order status are always computed by the backend, never taken from the AI. Replies that claim an action the AI did not actually take are blocked.
- **Payment flow** — DuitNow QR + reference sent automatically, optional unique amounts (e.g. RM10.03) to find the transfer quickly, and a 10-minute timer on every step.
- **Live owner dashboard** — Orders appear in real time with a sound and countdown on "Check payment"; Approve / Not received / Restore / Cancel in one click.
- **Menu editor** — Add and edit items, with a sold-out switch that the AI respects immediately.
- **Handoff to the owner** — Complaints and refund requests are passed to the owner, and the AI stops replying in that chat until **Resume AI**.
- **Multi-tenant** — Many businesses on one platform, each with its own menu, settings, orders and shop link.

### Tech Stack

| Layer         | Technology                                                                  |
| ------------- | --------------------------------------------------------------------------- |
| Frontend      | Next.js 16 (React 19, TypeScript), Tailwind CSS, shadcn/ui, TanStack Query  |
| Backend       | Python 3.12, FastAPI, SQLModel, Alembic                                     |
| Database      | PostgreSQL 16                                                               |
| Messaging     | Telegram Bot API (webhook)                                                  |
| AI / Compute  | Qwen2.5-7B-Instruct on RunPod (GPU), OpenAI-compatible API with tool calling |
| Hosting / Dev | Replit (Reserved VM)                                                        |

---

## Project Structure

```
.
├── docs/
│   └── TELEGRAM_SETUP.md    # Create the bot and connect it to the backend
├── runpod/
│   └── CLAUDE.md            # Fine-tuning + serving on RunPod
├── src/
│   ├── CLAUDE.md            # Start here: goals, rules, build order
│   ├── ARCHITECTURE.md      # System design, message flow, AI agent loop
│   ├── DATABASE.md          # Tables and relations
│   ├── API.md               # HTTP endpoints and AI tool contracts
│   ├── backend/             # FastAPI (Python)
│   │   └── CLAUDE.md
│   └── frontend/            # Next.js owner dashboard
│       └── CLAUDE.md
├── submission/              # Required submission documents
│   ├── SDC2026_TeamName_Preliminary.pdf      # Preliminary submission
│   ├── SDC2026_TeamName_TechDeclaration.pdf  # Technology declaration
│   ├── SDC2026_TeamName_Replit_POU.pdf       # Replit proof of use
│   └── SDC2026_TeamName_Runpod_POU.pdf       # RunPod proof of use
├── test/                    # Tests
├── .env.example             # Example environment variables
├── .gitignore
├── .replit                  # Replit run configuration
├── docker-compose.yml       # Local PostgreSQL
├── LICENSE
└── README.md
```

### Architecture

```
Customer (Telegram) ──► Telegram Bot API ──► Replit: FastAPI backend ──► RunPod endpoint (LLM)
        ▲                                     │        │
        └──── replies, QR, confirmation ──────┘        ├──► PostgreSQL (menus, orders, chats)
                                                       │
Owner ──► Waitly dashboard (Next.js) ◀── REST + live events ──┘
```

---

## How to Run

### Option 1 — Run on Replit (Recommended)

One process serves everything: the API, the Telegram webhook (`/telegram/webhook`), images (`/media`) and
the dashboard (a static Next.js export mounted by FastAPI at `/`). `.replit` holds the build and run
commands.

1. **Create Repl → Import from GitHub** and pick this repository (`main`).
2. Add a **PostgreSQL** database from the Database tool. Replit sets `DATABASE_URL` for you.
3. Open **Secrets** and add:

   | Secret | Value |
   | --- | --- |
   | `ENV` | `prod` (turns off `/dev/simulate`) |
   | `JWT_SECRET` | a long random string: `python -c "import secrets; print(secrets.token_hex(32))"` |
   | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | the RunPod endpoint (OpenAI-compatible) |
   | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` | from @BotFather, see `docs/TELEGRAM_SETUP.md` |
   | `TELEGRAM_WEBHOOK_SECRET` | a random string: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `TELEGRAM_DEFAULT_SHOP` | `kak-ani-kitchen` (the demo shop, for chats opened without a shop link) |
   | `PUBLIC_BASE_URL`, `FRONTEND_URL` | the published URL, e.g. `https://<app>.replit.app` |

4. **Publish → Reserved VM**. Use a Reserved VM, not Autoscale: the live dashboard events and the
   10-minute order timers run inside the one server process. The build exports the dashboard and
   installs the backend; each start runs the migrations and seeds the demo account
   (`demo@demo.my` / `demo1234`).
5. Nothing to set on Telegram's side: each start registers the webhook
   (`https://<app>.replit.app/telegram/webhook`) and logs every shop's link, e.g.
   `https://t.me/<bot>?start=kak-ani-kitchen`. Upload the payment QR in the dashboard's
   **Settings**, then open the link on a phone and order.

### Option 2 — Run Locally

Needs Docker, [uv](https://docs.astral.sh/uv/), Node.js and ngrok. Full steps: [How to Run (Local)](#how-to-run-local) below.

```bash
cp .env.example .env                                   # then fill in your values
docker compose up -d db                                # PostgreSQL
cd src/backend && uv sync && uv run alembic upgrade head && uv run python -m app.seed
uv run fastapi dev app/main.py --port 8000             # backend + Telegram webhook
# second terminal, from the repo root:
cd src/frontend && npm install && npm run dev          # dashboard on http://localhost:3000
```

### Run Tests

```bash
cd src/backend
uv run pytest                                # backend tests (fake LLM, no network)
uv run python -m app.evals.llm_scenarios     # real conversations against the RunPod model
```

---

## How We Use Replit _(Required)_

Describe how your team used Replit. For example:

- **Development:** Collaborative coding in a shared Repl using Multiplayer.
- **Hosting:** The app is deployed with Replit Deployments at the Live Demo link above.
- **Secrets:** API keys are stored in Replit Secrets, never in the code.

📄 Proof of use: [`submission/SDC2026_TeamName_Replit_POU.pdf`](submission/SDC2026_TeamName_Replit_POU.pdf)

## How We Use RunPod _(Required)_

Describe how your team used RunPod. For example:

- **Workload:** Model inference (e.g. text generation, image processing) runs on a RunPod GPU.
- **Setup:** `runpod/handler.py` is deployed as a **RunPod Serverless Endpoint**.
- **Integration:** The Replit app sends requests to the endpoint using `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`.

Example request:

```bash
curl -X POST https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/runsync \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": {"prompt": "Hello"}}'
```

📄 Proof of use: [`submission/SDC2026_TeamName_Runpod_POU.pdf`](submission/SDC2026_TeamName_Runpod_POU.pdf)

---

## Challenges & Learnings

- What challenges did you face, and how did you overcome them?
- What did your team learn?

## Future Improvements

- [ ] Improvement 1
- [ ] Improvement 2

## Team

| Name        | Role                | GitHub                                   |
| ----------- | ------------------- | ---------------------------------------- |
| Member Name | Team Lead / Backend | [@username](https://github.com/username) |
| Member Name | Frontend            | [@username](https://github.com/username) |
| Member Name | AI / RunPod         | [@username](https://github.com/username) |

---

## Submission Checklist

- [ ] Team name, domain (Domain 1 / Domain 2) and SDG track filled in
- [ ] Slide deck link added
- [ ] Demo video link added
- [ ] Replit used, with proof of use in `submission/`
- [ ] RunPod used, with proof of use in `submission/`
- [ ] Preliminary submission completed (`SDC2026_TeamName_Preliminary.pdf`)
- [ ] Technology declaration completed (`SDC2026_TeamName_TechDeclaration.pdf`)
- [ ] Submission files renamed with your team name (replace `TeamName`)
- [ ] "How to Run" steps verified
- [ ] No API keys or secrets committed to the repository

## License

This project is licensed under the [Apache License 2.0](LICENSE).

## How to Run (Local)

### Prerequisites

- Docker Desktop (running)
- [uv](https://docs.astral.sh/uv/) (Python)
- Node.js + npm
- ngrok

### First-time setup

```powershell
copy .env.example .env      # then fill in your values
cd src\backend
uv sync
cd ..\frontend
npm install
```

### Start the project

Run each block in its own terminal, starting from the repo root.

**1. Database**

```powershell
docker compose up -d db
cd src\backend
uv run alembic upgrade head
uv run python -m app.seed      # demo account + menu, prints the shop's Telegram link
```

**2. Backend** → http://localhost:8000 (docs at `/docs`)

```powershell
cd src\backend
uv run fastapi dev app/main.py --port 8000
```

**3. ngrok** (public https URL so Telegram can reach the webhook)

```powershell
ngrok http 8000
```

> Put the ngrok URL in `.env` as `PUBLIC_BASE_URL`, then (re)start the backend: it registers the
> Telegram webhook itself and logs the shop link (`Telegram link for Kak Ani Kitchen: ...`).
> Bot setup: `docs/TELEGRAM_SETUP.md`.

**4. Frontend** → http://localhost:3000

```powershell
cd src\frontend
npm run dev
```

Demo login: `demo@demo.my` / `demo1234`

### Stop the project

- Press `Ctrl+C` in the backend, ngrok and frontend terminals.
- Stop the database (data is kept in the `pgdata` volume):
  ```powershell
  docker compose down
  ```
  Don't add `-v`, because that deletes the database data.
