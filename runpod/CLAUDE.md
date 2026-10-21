# ML track — fine-tuning the order agent

The full plan (model choice, dataset, RunPod steps, evaluation, deployment) is in the team doc "Fine-tuning AI-агента для WhatsApp-заказов". This file only fixes the contract with the backend.

## Contract with the backend

- **Tool schemas**: the canonical list is in `../src/API.md` → "AI tools". Train with exactly those names and parameters. Note: `request_payment` and `mark_paid_by_customer` take **no parameters** (the backend binds the order).
- **System prompt**: generate training prompts with the same structure as `../src/backend/app/agent/prompt.py` (business name, menu JSON with `slug`, current cart, missing fields, rules). Import or copy it; do not invent a different format.
- **Tool results**: use the shapes in `../src/API.md` → "Tool results".
- **Serving**: OpenAI-compatible `/v1/chat/completions` with tool calling (vLLM). The backend switches by changing `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` only.

## Structure

```
runpod/
├── gen/            # synthetic dialogue generator + random menus + validator
├── data/           # train.jsonl, test.jsonl (test never used for training)
├── train/          # train.py for RunPod (Unsloth + TRL)
├── eval/           # eval.py: base vs fine-tuned, metrics table
└── serve/          # vLLM launch command and notes
```

Do not commit model weights or API keys. Push models to the team's private Hugging Face repo.
