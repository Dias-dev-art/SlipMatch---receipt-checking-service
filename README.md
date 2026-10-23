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

The payment proof that the Malaysian micro-sellers receive when they receive orders through WhatsApp are usually screenshots of the DuitNow or bank transaction, and dozens of times per day. For each of these, the owner must open a bank app and locate the corresponding transfer, and verify it against the right order, which requires 6 steps or so and is typically done late at night. It's slow and prone to error: an incorrect amount can be missed; failed payment or the same image twice and sellers could end up with goods sent to an empty wallet. It impacts home-based sellers, small caterers and other micro and small businesses without accounting employees or payment-gateway integrations.

### Solution

SlipMatch is an Orbyte module that leverages a vision AI model (Qwen2.5-VL-7B) on a dedicated RunPod endpoint to read payment-proof screenshots sent on WhatsApp. It captures the amount, the reference, the date and who it is for, and it compares these data with open invoices and bank statement based on 5 transparent rules: amount, reference, payee, date window and duplicate slip. Each slip has a status (Matched, Needs review or Suspicious) and simple language reasons, so the slip owner knows why. All payments are not recorded as paid until approved by the Owner, and all actions are stored in an audit log. If the model is unable to read a field, the slip is not guessed and it is sent to human review instead. A manual entry fallback is provided for the workflow if the AI endpoint is not available, with a clear and prominent label. The value is that AI covers part rules that cannot be covered (reading screenshots), rules and a human keep the decision accurate and accountable.

### Key Features

- **Feature 1** — Short description.
- **Feature 2** — Short description.
- **Feature 3** — Short description.

### Tech Stack

| Layer         | Technology      |
| ------------- | --------------- |
| Frontend      | HTML, React     |
| Backend       | Python, FastAPI |
| Database      | PostgreSQL      |
| AI / Compute  | RunPod (GPU)    |
| Hosting / Dev | Replit          |

---

## Project Structure

```
.
├── docs/                    # Screenshots, diagrams
├── runpod/
│   ├── CLAUDE.md            # Fine-tuning + serving on RunPod
│   └── handler.py           # RunPod serverless handler (GPU workload)
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
User ──► Replit (App / API) ──► RunPod Endpoint (GPU model)
                │
                └──► Response returned to user
```

---

## How to Run

### Option 1 — Run on Replit (Recommended)

1. Open the [Replit Project](https://replit.com/@your-username/your-project), or import this repository via **Create Repl → Import from GitHub**.
2. Open the **Secrets** tab (🔒) and add the variables listed in `.env.example`:
   - `RUNPOD_API_KEY`
   - `RUNPOD_ENDPOINT_ID`
3. Click **Run**. Replit uses the `.replit` file to start `python src/main.py`.

### Option 2 — Run Locally

```bash
# 1. Clone the repository
git clone https://github.com/your-username/your-project.git
cd your-project

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env            # then fill in your values

# 5. Run the app
python src/main.py
```

### Run Tests

```bash
python -m unittest discover test
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
```

**2. Backend** → http://localhost:8000 (docs at `/docs`)

```powershell
cd src\backend
uv run fastapi dev app/main.py --port 8000
```

**3. ngrok** (public URL for the WhatsApp webhook)

```powershell
ngrok http 8000
```

> If the ngrok URL changes:
>
> 1. Update `PUBLIC_BASE_URL` in `.env`.
> 2. Restart the backend.
> 3. Update the webhook URL in the Meta dashboard.

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
