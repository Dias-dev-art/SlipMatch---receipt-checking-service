"""run_agent(): LLM chats and picks tool calls; Python executes them; repeat until a text reply."""

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.agent import intents
from app.agent.executor import ToolContext, execute_tool, resend_payment_details
from app.agent.llm import AssistantTurn, LLMError, ToolCall, get_llm_client
from app.agent.prompt import build_system_prompt
from app.agent.tools import TOOL_NAMES, TOOLS
from app.models import OrderStatus
from app.models.base import utcnow
from app.services import orders, templates
from app.services.menu import available_items

log = logging.getLogger(__name__)

MAX_ITERATIONS = 6
_TOOL_NAME_RE = re.compile(r"\b(" + "|".join(TOOL_NAMES) + r")\b")
CORRECTION = (
    "Your last message was NOT sent to the customer ({reason}). To change the order or mark it "
    "paid, use a real tool call. Never say a payment is received or confirmed: the owner checks "
    "the bank. Otherwise reply again in plain, short words."
)
UNBACKED_CORRECTION = (
    "Your last message was NOT sent: it says you added items, saved an address, gave a total or "
    "sent payment details, but you called no tool, so nothing happened. If the customer asked "
    "for items, call add_item now. If they gave an address, call set_address. If they said "
    "pickup or delivery, call set_order_type. If they are finished, call request_payment. "
    "Otherwise reply without claiming anything was done."
)
STATUS_CORRECTION = (
    "Your last message was NOT sent: never say the order is confirmed, ready or on its way. "
    "The owner confirms it after checking the payment. Reply again in plain, short words."
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

# Food readiness and delivery are the owner's call, never the AI's. Such sentences are dropped
# from the reply ("The owner will check it. Your order is on the way!" -> first sentence only).
_STATUS_CLAIM_RE = re.compile(
    r"on (its|their|the) way|enjoy your (meal|food)|order (is|has been) (now )?(confirmed|ready)"
    r"|\bis ready for (pick ?up|collection)|mark (it|this|the payment) as (received|paid)"
    r"|will be ready|ready soon|(siap|sedia) untuk diambil"
    # made-up promises, seen live: "Expected delivery time: 30-45 minutes"
    r"|delivery time|\d+\s*(-|–|to)\s*\d+\s*(min|minit)"
    r"|(pesanan|order) (anda )?(telah|sudah|dah) (disahkan|dihantar)|dalam perjalanan",
    re.IGNORECASE,
)
# line breaks end a sentence too: seen live, the model copied the code-written cart summary
# ("Your order:\n• ...\nTotal: RM21.00\nPickup or delivery?") without calling any tool
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|\s*\n\s*")
# internals the customer must never see: menu ids like "mee_goreng", the word "id"
_INTERNAL_RE = re.compile(r"\b[a-z]+_[a-z_]+\b|\bid\b", re.IGNORECASE)
# Claims that only make sense after a tool ran in this turn (seen live: "Adding one Roti Canai",
# "Your total is RM17.00", "Here's the QR code [QR Code Image]" with no tool call at all).
_UNBACKED_CLAIM_RE = re.compile(
    r"\b(added|adding|ditambah|dimasukkan)\b|saya (sudah |dah |telah )?(tambah|masukkan)"
    r"|coming (right )?up|\bQR\b|reference [A-Z]\d{3}"
    r"|\b(noted|dicatat|disimpan)\b|(address|alamat)\w* (is |has been |telah |sudah )?(saved|set)",
    re.IGNORECASE,
)
# "your total is RM17.00": fine when it is the real cart total, made up otherwise
_TOTAL_RE = re.compile(r"\btotal\w*\b[^.\n]{0,25}?RM ?(\d+(?:\.\d{1,2})?)", re.IGNORECASE)

# Small models sometimes answer with just the name of a no-argument tool instead of calling it.
# Running it through the normal executor is safe: the backend still validates everything.
RECOVERABLE_TEXT_TOOLS = ("request_payment", "mark_paid_by_customer")


def text_tool(reply: str) -> str | None:
    """The tool name if the whole reply is just a no-argument tool name, else None."""
    name = reply.strip().strip("`*\"'.!() \n").lower()
    return name if name in RECOVERABLE_TEXT_TOOLS else None


def text_tool_calls(reply: str) -> list[ToolCall]:
    """Tool calls the model wrote as text, Hermes style: '<tool_call>{"name": ..., ...}'.

    Seen live from the Qwen endpoint. They run through the normal executor, which validates them.
    """
    calls: list[ToolCall] = []
    decoder = json.JSONDecoder()
    for n, part in enumerate(reply.split("<tool_call>")[1:]):
        start = part.find("{")
        if start < 0:
            continue
        try:
            data, _ = decoder.raw_decode(part[start:])
        except ValueError:
            continue
        name = data.get("name") if isinstance(data, dict) else None
        if name not in TOOL_NAMES:
            continue
        args = data.get("arguments") or {}
        arguments = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        calls.append(ToolCall(id=f"text_{n}", name=name, arguments=arguments))
    return calls


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END_RE.split(text.strip()) if s]


def drop_bad_sentences(reply: str) -> str:
    """The reply without sentences only the owner may say (confirmed, ready, paid) or that leak
    internals. Seen live: "Marking as paid by customer. Thank you!" and 'I used id "mee_goreng"'.
    """
    sentences = _sentences(reply)
    kept = [
        s
        for s in sentences
        if not (_STATUS_CLAIM_RE.search(s) or _PAYMENT_CLAIM_RE.search(s) or _INTERNAL_RE.search(s))
    ]
    if len(kept) == len(sentences):
        return reply.strip()  # keep the line breaks the later checks rely on
    return "\n".join(kept).strip()


def invalid_reply(
    reply: str, *, acted: bool = True, totals: frozenset[Decimal] = frozenset()
) -> str | None:
    """Why this reply must not reach the customer, or None if it is fine.

    `acted`: a tool ran in this turn. Without one, the reply must not claim the order changed.
    `totals`: the real subtotal/total of the current order, which the reply may quote.
    """
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
    if _STATUS_CLAIM_RE.search(text):
        return "claims_order_status"
    if not acted:
        # questions are offers, not claims: "Shall I add 2 Mee Goreng for you?"
        for sentence in (s for s in _sentences(text) if not s.endswith("?")):
            if _UNBACKED_CLAIM_RE.search(sentence):
                return "claims_without_tool"
            if any(Decimal(m) not in totals for m in _TOTAL_RE.findall(sentence)):
                return "claims_without_tool"
    return None


def _order_totals(ctx: ToolContext) -> frozenset[Decimal]:
    order = ctx.order
    return frozenset({order.subtotal, order.total}) if order else frozenset()


_CORRECTIONS = {
    "claims_without_tool": UNBACKED_CORRECTION,
    "claims_order_status": STATUS_CORRECTION,
}


def _last_texts(history: list[dict[str, Any]]) -> tuple[str, str | None]:
    """The customer's message this turn and the AI's reply before it."""
    customer = history[-1]["content"] if history and history[-1]["role"] == "user" else ""
    previous = next(
        (m["content"] for m in reversed(history[:-1]) if m["role"] == "assistant"), None
    )
    return customer or "", previous


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
    # sold out = the AI stops offering it
    menu = available_items(ctx.session, ctx.business.id)
    order = ctx.order
    lines = orders.cart_lines(ctx.session, order) if order else []
    missing = orders.missing_fields(ctx.session, order)
    return build_system_prompt(
        ctx.business, list(menu), order, lines, missing, first_message=first_message
    )


CART_TOOLS = ("add_item", "remove_item", "set_order_type", "set_address")
_SHORT_OPENER_WORDS = 8


def _opener(reply: str) -> str:
    """The AI's friendly opening ("Boleh boss!", "Great choice!") without anything about the cart.

    Seen live: after a real tool call the model still described a cart that did not exist
    ("One Besh and one Mee Goreng are added" with only Besh in it), so its sentences about the
    order are dropped; the code-written summary below says what is really in the cart.
    """
    kept = []
    first_line = reply.strip().split("\n", 1)[0]
    for sentence in _sentences(first_line):
        if (
            len(sentence.split()) > _SHORT_OPENER_WORDS
            or sentence.endswith(("?", ":"))
            or "RM" in sentence
            or _UNBACKED_CLAIM_RE.search(sentence)
        ):
            break
        kept.append(sentence)
    return " ".join(kept) or "Got it! 👍"


def fill_only_order_type(ctx: ToolContext) -> None:
    """A shop that offers only pickup (or only delivery): code sets it, the customer isn't asked."""
    order, business = ctx.order, ctx.business
    if order is None or order.order_type is not None or order.status != OrderStatus.chatting:
        return
    if business.pickup_enabled != business.delivery_enabled:
        only = "pickup" if business.pickup_enabled else "delivery"
        execute_tool(ctx, "set_order_type", {"type": only})


def with_cart_summary(ctx: ToolContext, reply: str, *, by_code: bool = False) -> str:
    """Opener + the real cart + the next question, all but the opener written by code.

    `by_code`: the reply was written by code (a template), so it is kept whole.
    """
    fill_only_order_type(ctx)
    order = ctx.order
    if order is None:
        return reply
    lines = orders.cart_lines(ctx.session, order)
    missing = orders.missing_fields(ctx.session, order)
    return "\n\n".join(
        [
            reply if by_code else _opener(reply),
            templates.cart_summary(order, lines),
            templates.next_question(missing),
        ]
    )


def _add_items_by_code(ctx: ToolContext, text: str, trace: list[dict[str, Any]]) -> bool:
    """The model said it added items but called no tool: read them from the customer's message.

    Only the customer's words count, never the model's; add_item still validates everything.
    """
    found = intents.parse_items(text, available_items(ctx.session, ctx.business.id))
    added = False
    for slug, qty in found:
        result = execute_tool(ctx, "add_item", {"menu_item_id": slug, "qty": qty})
        trace.append({"code_add_item": slug, "qty": qty, "result": result})
        added = added or bool(result.get("ok"))
    return added


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
    turn_start = len(messages)  # messages from here on belong to this turn
    trace: list[dict[str, Any]] = []
    corrected = False
    recovered = False
    acted = False
    cart_changed = False  # then the reply gets the code-written cart summary

    customer_text, previous_reply = _last_texts(history)

    def run_by_code(name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        """Show the model a step code already took, as if it had called the tool itself."""
        call = ToolCall(id=f"code_{len(trace)}", name=name, arguments=json.dumps(args))
        trace.append({"iteration": -1, "code_tool": name, "arguments": args, "result": result})
        messages.append(AssistantTurn(tool_calls=[call]).as_message())
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

    # "can you pass me to the owner": seen live, the model wrote "Handing over..." and did not
    if intents.wants_owner(customer_text):
        args = {"reason": "The customer asked to talk to the owner."}
        run_by_code("handoff_to_owner", args, execute_tool(ctx, "handoff_to_owner", args))
        return AgentResult(Outcome.handoff, templates.HANDOFF, trace)

    # pickup / delivery from the customer's own words, only if this shop offers it
    # (seen live: "Delivery" was accepted with delivery switched off)
    wanted = intents.order_type_said(customer_text)
    if wanted:
        offered = (
            ctx.business.delivery_enabled if wanted == "delivery" else ctx.business.pickup_enabled
        )
        if not offered:
            fill_only_order_type(ctx)
            reply = templates.order_type_unavailable(ctx.business, wanted)
            trace.append({"iteration": -1, "order_type_not_offered": wanted})
            if ctx.order is not None and orders.cart_lines(ctx.session, ctx.order):
                reply = with_cart_summary(ctx, reply, by_code=True)
            return AgentResult(Outcome.reply, reply, trace)
        order = ctx.order
        if order is None or (order.status == OrderStatus.chatting and order.order_type != wanted):
            args = {"type": wanted}
            result = execute_tool(ctx, "set_order_type", args)
            run_by_code("set_order_type", args, result)
            acted = True
            cart_changed = bool(result.get("ok"))

    # code takes the checkout and "I paid" steps itself; the LLM then only adds a friendly line
    order = ctx.order
    missing = orders.missing_fields(ctx.session, order) if order else []
    action = intents.auto_action(order, missing, customer_text, previous_reply)
    if not action and intents.asks_for_menu(customer_text):
        menu = available_items(ctx.session, ctx.business.id)
        if not intents.parse_items(customer_text, menu):
            # the real menu, never the model's: seen live, it invented 4 items for a 1-item menu
            trace.append({"iteration": -1, "menu_by_code": True})
            return AgentResult(Outcome.reply, templates.menu_reply(menu), trace)
    if action:
        if action == "resend_payment":
            result = resend_payment_details(ctx)
            action = "request_payment"  # what the model sees: payment details were sent
        else:
            result = execute_tool(ctx, action, {})
        recovered = acted = True
        call = ToolCall(id="auto_0", name=action, arguments="{}")
        trace.append({"iteration": -1, "auto_tool": action, "result": result})
        messages.append(AssistantTurn(tool_calls=[call]).as_message())
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )
        if result.get("error") == "phone_needed":
            # the "Share phone number" button is the whole answer; the QR follows when tapped
            return AgentResult(Outcome.reply, None, trace)

    for iteration in range(MAX_ITERATIONS):
        # refresh every iteration: the cart may have changed after tool calls
        messages[0]["content"] = _system_prompt(ctx, first_message)
        try:
            turn = llm.chat(messages, TOOLS)
        except LLMError as exc:
            return _fallback(ctx, trace, f"llm_error: {exc}"[:200])

        if not turn.tool_calls and (written := text_tool_calls(turn.content or "")):
            trace.append({"iteration": iteration, "text_tool_calls": len(written)})
            turn = AssistantTurn(tool_calls=written)

        if not turn.tool_calls:
            raw = (turn.content or "").strip()
            reply = drop_bad_sentences(raw) or raw
            trace.append({"iteration": iteration, "reply": raw})
            if reply != raw:
                trace.append({"iteration": iteration, "dropped_sentences": True})
            if not reply:
                return _fallback(ctx, trace, "empty_reply")
            name = None if recovered else text_tool(reply)
            if name:
                # once per turn: run it as if it had been a real tool call
                recovered = acted = True
                call = ToolCall(id=f"recovered_{iteration}", name=name, arguments="{}")
                result = intents.premature_tool(
                    name, customer_text, previous_reply
                ) or execute_tool(ctx, name, {})
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
            problem = invalid_reply(reply, acted=acted, totals=_order_totals(ctx))
            if (
                problem == "claims_without_tool"
                and not corrected
                and _add_items_by_code(ctx, customer_text, trace)
            ):
                return AgentResult(Outcome.reply, with_cart_summary(ctx, reply), trace)
            if problem:
                if corrected:
                    if problem == "claims_without_tool":
                        # nothing harmful happened; ask again instead of silencing the chat
                        trace.append({"iteration": iteration, "gave_up": problem})
                        return AgentResult(Outcome.reply, templates.ASK_AGAIN, trace)
                    return _fallback(ctx, trace, problem)
                corrected = True
                trace.append({"iteration": iteration, "correction": problem})
                if problem == "claims_without_tool":
                    # seen live: a 7B model copies its own old "Adding one ..." replies from the
                    # history; retry with only this turn so it has nothing to copy
                    messages[:] = [messages[0], *history[-1:], *messages[turn_start:]]
                    turn_start = len(messages)
                messages.append({"role": "assistant", "content": reply})
                correction = _CORRECTIONS.get(problem) or CORRECTION.format(reason=problem)
                messages.append({"role": "system", "content": correction})
                continue
            if cart_changed:
                reply = with_cart_summary(ctx, reply)
            return AgentResult(Outcome.reply, reply, trace)

        messages.append(turn.as_message())
        acted = True
        for call in turn.tool_calls:
            result = intents.premature_tool(
                call.name, customer_text, previous_reply
            ) or execute_tool(ctx, call.name, call.arguments)
            cart_changed = cart_changed or (call.name in CART_TOOLS and bool(result.get("ok")))
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
        if any(
            step.get("tool") == "request_payment" and step["result"].get("error") == "phone_needed"
            for step in trace
        ):
            # the cart summary + "Share phone number" button already went out
            return AgentResult(Outcome.reply, None, trace)
        if ctx.handoff:
            return AgentResult(Outcome.handoff, templates.HANDOFF, trace)

    return _fallback(ctx, trace, "iteration_limit")
