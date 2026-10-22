"""run_agent(): LLM chats and picks tool calls; Python executes them; repeat until a text reply."""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlmodel import col, select

from app.agent.executor import ToolContext, execute_tool
from app.agent.llm import AssistantTurn, LLMError, ToolCall, get_llm_client
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOL_NAMES, TOOLS
from app.models import MenuItem
from app.models.base import utcnow
from app.services import orders, templates

log = logging.getLogger(__name__)

MAX_ITERATIONS = 6
_TOOL_NAME_RE = re.compile(r"\b(" + "|".join(TOOL_NAMES) + r")\b")
CORRECTION = (
    "Your last message was NOT sent to the customer ({reason}). To change the order or mark it "
    "paid, use a real tool call. Never say a payment is received or confirmed: the owner checks "
    "the bank. Otherwise reply again in plain, short words."
)


# "The AI must never say payment received" (ARCHITECTURE.md): only the owner confirms.
_PAYMENT_CLAIM_RE = re.compile(
    r"payment (has been |is |was )?(received|confirmed|verified)"
    r"|\bas paid\b"  # "marked as paid", "Marking your order as paid"
    r"|order (is|has been|was) (now )?paid"
    r"|payment (was|has been) (successful|completed?)"
    r"|pembayaran (anda )?(telah |sudah |dah )?(diterima|disahkan|berjaya)"
    r"|terima kasih atas pembayaran|bayaran (telah |sudah |dah )?diterima"
    r"|sebagai (telah |sudah |dah )?(di)?bayar"  # "kami markas sebagai sudah bayar"
    r"|(order|pesanan) (anda |awak )?(telah|sudah|dah) (di)?bayar"
    # "Saya sudah mendaftar pembayaran anda"
    r"|(telah|sudah|dah) (\w+ )?(mendaftar|merekod|mencatat|terima|menerima) (\w+ )?pembayaran",
    re.IGNORECASE,
)

# Small models sometimes answer with just the name of a no-argument tool instead of calling it.
# Running it through the normal executor is safe: the backend still validates everything.
RECOVERABLE_TEXT_TOOLS = ("request_payment", "mark_paid_by_customer")


def text_tool(reply: str) -> str | None:
    """The tool name if the whole reply is just a no-argument tool name, else None."""
    name = reply.strip().strip("`*\"'.!() \n").lower()
    return name if name in RECOVERABLE_TEXT_TOOLS else None


def invalid_reply(reply: str) -> str | None:
    """Why this reply must not reach the customer, or None if it is fine."""
    text = reply.strip()
    # small models sometimes write the tool call as text instead of calling it
    # ('/ionorf {"reason": ...}' was seen live); a customer reply never needs JSON
    if (
        _TOOL_NAME_RE.search(text)
        or "<tool_call>" in text
        or text.startswith(("{", "[", "```"))
        or '{"' in text
    ):
        return "tool_text_in_reply"
    if "<|" in text or "|>" in text:  # chat-template tokens: the model degenerated
        return "special_tokens_in_reply"
    if _PAYMENT_CLAIM_RE.search(text):
        return "claims_payment_received"
    return None


class Outcome(StrEnum):
    reply = "reply"
    ignored = "ignored"  # not an order: send nothing
    handoff = "handoff"  # owner takes over: fixed template, AI goes silent
    fallback = "fallback"  # LLM failed or looped: fixed template + needs_owner


@dataclass
class AgentResult:
    outcome: Outcome
    reply: str | None
    trace: list[dict[str, Any]] = field(default_factory=list)


def _system_prompt(ctx: ToolContext, first_message: bool) -> str:
    menu = ctx.session.exec(
        select(MenuItem)
        .where(
            MenuItem.business_id == ctx.business.id,
            col(MenuItem.is_available).is_(True),  # sold out = the AI stops offering it
            col(MenuItem.deleted_at).is_(None),
        )
        .order_by(col(MenuItem.sort_order), col(MenuItem.name))
    ).all()
    order = ctx.order
    lines = orders.cart_lines(ctx.session, order) if order else []
    missing = orders.missing_fields(ctx.session, order)
    return build_system_prompt(
        ctx.business, list(menu), order, lines, missing, first_message=first_message
    )


def _fallback(ctx: ToolContext, trace: list[dict[str, Any]], reason: str) -> AgentResult:
    ctx.conversation.needs_owner = True
    ctx.conversation.handoff_reason = reason
    ctx.conversation.handoff_at = utcnow()
    ctx.session.add(ctx.conversation)
    ctx.flags.append("conversation.needs_owner")
    trace.append({"fallback": reason})
    return AgentResult(Outcome.fallback, templates.FALLBACK, trace)


def run_agent(
    ctx: ToolContext, history: list[dict[str, Any]], *, first_message: bool = False
) -> AgentResult:
    llm = get_llm_client()
    messages: list[dict[str, Any]] = [{"role": "system", "content": ""}, *history]
    trace: list[dict[str, Any]] = []
    corrected = False
    recovered = False

    for iteration in range(MAX_ITERATIONS):
        # refresh every iteration: the cart may have changed after tool calls
        messages[0]["content"] = _system_prompt(ctx, first_message)
        try:
            turn = llm.chat(messages, TOOLS)
        except LLMError as exc:
            return _fallback(ctx, trace, f"llm_error: {exc}"[:200])

        if not turn.tool_calls:
            reply = (turn.content or "").strip()
            trace.append({"iteration": iteration, "reply": reply})
            if not reply:
                return _fallback(ctx, trace, "empty_reply")
            name = None if recovered else text_tool(reply)
            if name:
                # once per turn: run it as if it had been a real tool call
                recovered = True
                call = ToolCall(id=f"recovered_{iteration}", name=name, arguments="{}")
                result = execute_tool(ctx, name, {})
                trace.append(
                    {"iteration": iteration, "recovered_text_tool": name, "result": result}
                )
                messages.append(AssistantTurn(tool_calls=[call]).as_message())
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                continue
            problem = invalid_reply(reply)
            if problem:
                if corrected:
                    return _fallback(ctx, trace, problem)
                corrected = True
                trace.append({"iteration": iteration, "correction": problem})
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "system", "content": CORRECTION.format(reason=problem)})
                continue
            return AgentResult(Outcome.reply, reply, trace)

        messages.append(turn.as_message())
        for call in turn.tool_calls:
            result = execute_tool(ctx, call.name, call.arguments)
            trace.append(
                {
                    "iteration": iteration,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        if ctx.ignored:
            return AgentResult(Outcome.ignored, None, trace)
        if ctx.handoff:
            return AgentResult(Outcome.handoff, templates.HANDOFF, trace)

    return _fallback(ctx, trace, "iteration_limit")
