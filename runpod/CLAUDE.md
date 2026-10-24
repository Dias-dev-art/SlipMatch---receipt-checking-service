# ML track — fine-tuning the order agent

The full plan (model choice, dataset, RunPod steps, evaluation, deployment) is in the team doc "Fine-tuning AI-агента для WhatsApp-заказов". This file only fixes the contract with the backend.

## Contract with the backend

- **Tool schemas**: the canonical list is in `../src/API.md` → "AI tools". Train with exactly those names and parameters. Note: `request_payment` and `mark_paid_by_customer` take **no parameters** (the backend binds the order).
- **System prompt**: generate training prompts with the same structure as `../src/backend/app/agent/prompt.py` (business name, menu JSON with `slug`, current cart, missing fields, rules). Import or copy it; do not invent a different format.
- **Channel + persona (2026-10-25)**: customers now order through Telegram, not WhatsApp, and the agent should sound like a friendly waiter. Do NOT put that in the prompt: any tone/persona line (even "call add_item every time") dropped `add_item` on "1 teh tarik" from 8/8 to 0-4/6 (table in `src/ARCHITECTURE.md`). Teach the warm style through the dataset's assistant replies instead. Small talk now gets a short reply that asks what they would like to order (no `ignore_or_flag`). `ignore_or_flag` is only for spam/abuse now, and `handoff_to_owner` only for complaints/refunds/angry customers. The backend now runs `request_payment` / `mark_paid_by_customer` itself on clear phrases (`app/agent/intents.py`), but the model should still learn them. Regenerate the dataset with the new prompt.
- **Tool results**: use the shapes in `../src/API.md` → "Tool results".
- **Serving**: OpenAI-compatible `/v1/chat/completions` with tool calling (vLLM). The backend switches by changing `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` only.

## Evaluating a model

From `src/backend`, with `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` in the repo `.env`:

```bash
uv run python -m app.evals.llm_scenarios        # 8 real conversations, PASS/FAIL per scenario
```

It runs the real backend pipeline (prompt, tools, validator, reply guard) on its own test business.
A model is ready for the demo when every scenario passes. Per-turn traces (tool calls, blocked
replies, fallbacks) are printed; the same traces are stored in `messages.payload`.

## Known failures to train on (Qwen/Qwen2.5-7B-Instruct endpoint, 2026-10-22)

The endpoint reports the model id `Qwen/Qwen2.5-7B-Instruct`; check it is really the fine-tune.
Each item: what the customer said → what the model did → what the dataset must teach.

1. Cart complete, customer says "itu je" / "ok tu je" / "that's all" → model asks "ready to pay?"
   or writes `request_payment` as plain text → **call `request_payment`** (real tool call, no text).
   The backend now runs a reply that is exactly a no-argument tool name, but don't rely on it.
2. "dah bayar" → model replies "Marking as paid…" / "order anda kami markas sebagai sudah bayar" /
   "Saya sudah mendaftar pembayaran anda" → **call `mark_paid_by_customer`**, then a short line like
   "Thanks, the owner will check the payment." Never say paid/received/confirmed in any language.
3. "ada nasi ayam?" (not on menu) → model added `nasi_lemak` to the cart → **no `add_item`**; say it
   is not on the menu and suggest items from MENU.
4. Small talk ("bro jom lepak mamak") → model wrote `/ionorf {"reason": …}` as text → with the
   waiter persona: **a short friendly reply that leads back to the menu**, no tool call, nothing in
   the cart (eval scenario f). `ignore_or_flag` is for spam and abuse only.
5. After a cart change cancels a payment request, the model repeated "Pay RM11.00, reference L018"
   by itself → **call `request_payment` again**; never write amounts or references in text.
6. Mixed Indonesian ("mengandung", "porsi", "Tekan Ya") → stay with Malaysian Malay/Manglish; there
   are no buttons.
7. Calls `set_order_type` again on "itu je" when the type is already set → not needed; check
   `missing_fields` in CURRENT ORDER.

Latency: usually 1.5–7 s per turn, but some turns took 40 s+ (RunPod queue / cold workers). The
backend timeout is 60 s with 2 retries (`app/agent/llm.py`); keep a warm worker for the demo.

## Structure

```
runpod/
├── order_ai25.py   # ML teammate's order reader (see below), kept as a reference
├── chat5.py        # terminal chat for it
├── eval_orders9.py # its evaluation script
│   planned, not committed yet:
├── gen/            # synthetic dialogue generator + random menus + validator
├── data/           # train.jsonl, test.jsonl (test never used for training)
├── train/          # train.py for RunPod (Unsloth + TRL)
├── eval/           # eval.py: base vs fine-tuned, metrics table
└── serve/          # vLLM launch command and notes
```

### The teammate's order reader (2026-10-25)

`order_ai25.py`, `chat5.py`, `eval_orders9.py` are **prompt tuning, not fine-tuning**: there is
no training data or training script, and the model is the stock Qwen 2.5 7B on RunPod. They come
from the earlier SlipMatch / WhatsApp design: the AI only *reads* a message into JSON (items +
quantities, `response_format` json_schema), plain Python decides (ACCEPT / PARTIAL / DECLINE /
NEEDS_REVIEW, against stock in `data/menu.csv`) and every reply is a template. They do not run
as committed: `chat5.py` / `eval_orders9.py` import `order_ai` and `sessions`, and need
`data/menu.csv`, `data/test_orders.csv` and `data/wiki_cache.json`, which were not shared.

The backend keeps its own flow (cart, pickup/delivery, phone, payment, dashboard) and borrowed
two ideas into `src/backend/app/agent/intents.py`: **unit words** ("2 bungkus nasi lemak" = 2)
and **negation** ("tak nak teh tarik", "no fries" = not ordered). The same "AI reads, code
decides" idea is what the backend's code-decided steps do (cart summary, checkout, paid, menu,
owner, pickup/delivery).

Do not commit model weights or API keys. Push models to the team's private Hugging Face repo.
