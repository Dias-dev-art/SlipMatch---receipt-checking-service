"""Real conversations against the configured LLM (`LLM_*` in .env), with pass/fail checks.

    uv run python -m app.evals.llm_scenarios          # all scenarios
    uv run python -m app.evals.llm_scenarios a c f    # some of them

Runs the real pipeline in-process (same code as /dev/simulate and the Telegram webhook) on its own
business "LLM Eval Kitchen" in the dev database, wiped at the start of every run. Use it to
compare model versions: every scenario should PASS before a model is used for the demo.
"""

import sys
import time
from dataclasses import dataclass, field
from decimal import Decimal

from sqlmodel import Session, col, select

from app.api.v1.dev import reset
from app.core.config import settings
from app.core.db import engine
from app.core.security import hash_password
from app.models import Business, MenuItem, Message, Owner
from app.seed import MENU
from app.services.pipeline import CollectingOutbox, IncomingMessage, handle_incoming

EVAL_EMAIL = "llm-eval@eval.local"
ANY = "any"


@dataclass
class Scenario:
    key: str
    title: str
    turns: list[str]
    status: str | None = ANY  # final order status; None = no order was created
    total: str | None = None
    outcome: str | None = None  # outcome of the last turn
    not_status: str | None = None  # final order status that would be wrong
    no_items: bool = False  # the AI must not put anything in the cart


SCENARIOS = [
    Scenario(
        "a",
        "Pickup happy path",
        ["boss nak 2 nasi lemak tapau", "itu je", "dah bayar"],
        status="payment_check",
        total="16.00",
    ),
    Scenario(
        "b",
        "Delivery with address",
        ["1 mee goreng 1 teh tarik, hantar ye", "12 Jalan Bunga, Taman Melati", "ok tu je"],
        status="awaiting_payment",
        total="13.00",
    ),
    Scenario("c", "Not on menu", ["ada nasi ayam?"], status=None, no_items=True),
    Scenario("d", "Menu question", ["mee goreng pedas tak? ada telur?"], outcome="reply"),
    Scenario(
        "e",
        "Change after payment request",
        ["1 nasi lemak tapau", "ok itu sahaja, nak bayar", "eh tambah 1 teh tarik"],
        status="chatting",
        total="11.00",
    ),
    # a waiter answers small talk warmly and steers back to the menu; nothing goes in the cart
    Scenario(
        "f",
        "Small talk",
        ["bro jom lepak mamak malam ni"],
        status=None,
        outcome="reply",
        no_items=True,
    ),
    Scenario("g", "Complaint", ["makanan semalam basi, nak refund"], outcome="handoff"),
    # payment was never requested, so "paid" must not reach the owner's Check payment column
    Scenario(
        "h",
        "Says paid before paying",
        ["2 roti canai tapau", "dah bayar"],
        not_status="payment_check",
    ),
    Scenario(
        "i", "Asks for a recommendation", ["hi, what's good here?"], outcome="reply", no_items=True
    ),
    # seen live 2026-10-25: the second request got no add_item call at all
    Scenario(
        "j",
        "Adds more items later",
        ["one nasi lemak", "can I also add one mee goreng and 2 teh tarik"],
        status="chatting",
        total="21.00",
    ),
    # seen live 2026-10-26: invented menu items, and "pass me to the owner" was not handed off
    Scenario("k", "Asks for the menu", ["whats the menu?"], outcome="reply", no_items=True),
    Scenario("l", "Asks for the owner", ["can you pass me to the owner"], outcome="handoff"),
]


@dataclass
class Result:
    scenario: Scenario
    problems: list[str] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)


def eval_business(session: Session) -> Business:
    owner = session.exec(select(Owner).where(Owner.email == EVAL_EMAIL)).first()
    if owner is None:
        owner = Owner(
            email=EVAL_EMAIL, hashed_password=hash_password("not-for-login"), full_name="Eval"
        )
        session.add(owner)
        session.flush()
    business = session.exec(select(Business).where(Business.owner_id == owner.id)).first()
    if business is None:
        business = Business(
            owner_id=owner.id,
            name="LLM Eval Kitchen",
            delivery_enabled=True,
            delivery_fee=Decimal("3.00"),
            payment_instructions="DuitNow to LLM Eval Kitchen, Bank Harimau 1234567890",
        )
        session.add(business)
        session.flush()
        for sort, (slug, name, price, description, tags, category) in enumerate(MENU, start=1):
            session.add(
                MenuItem(
                    business_id=business.id,
                    slug=slug,
                    name=name,
                    price=Decimal(price),
                    description=description,
                    tags=tags,
                    category=category,
                    sort_order=sort,
                )
            )
    session.commit()
    return business


def _trace(session: Session, conversation_id) -> list[dict]:
    msg = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id, col(Message.payload).is_not(None))
        .order_by(col(Message.created_at).desc())
    ).first()
    return (msg.payload or {}).get("trace", []) if msg else []


def _print_trace(trace: list[dict]) -> None:
    last_reply = ""
    for step in trace:
        if "reply" in step:
            last_reply = step["reply"]
        elif "tool" in step:
            res = step["result"]
            short = res.get("error") or (
                f"ok total={res.get('total')} missing={res.get('missing_fields')}"
                if "cart" in res
                else "ok"
            )
            print(f"      tool {step['tool']}({step['arguments']}) -> {short}")
        elif "recovered_text_tool" in step:
            print(f"      RECOVERED tool written as text: {step['recovered_text_tool']}")
        elif "correction" in step:
            print(f"      GUARD blocked reply ({step['correction']}): {last_reply!r}")
        elif "fallback" in step:
            print(f"      FALLBACK: {step['fallback']}")


def run(scenario: Scenario, session: Session, business: Business, chat_id: str) -> Result:
    result = Result(scenario)
    print(f"\n=== {scenario.key}. {scenario.title} ===")
    outcome, order = None, None
    for text in scenario.turns:
        outbox = CollectingOutbox()
        started = time.perf_counter()
        res = handle_incoming(
            session,
            IncomingMessage(business_id=business.id, chat_id=chat_id, text=text, phone=chat_id),
            outbox,
        )
        result.seconds.append(time.perf_counter() - started)
        outcome, order = res.outcome, res.order
        print(f"  > {text}")
        if res.conversation_id:
            _print_trace(_trace(session, res.conversation_id))
        for sent in outbox.sent:
            label = "IMG" if sent["type"] == "image" else "out"
            print(f"  < [{label}] {sent.get('text') or sent.get('url')}")
        print(
            f"    [{outcome}] status={order and order.status.value} "
            f"total={order and order.total} ({result.seconds[-1]:.1f}s)"
        )
        if outcome == "fallback" and scenario.outcome != "fallback":
            result.problems.append(f"fallback on {text!r}")

    status = order.status.value if order else None
    if scenario.status != ANY and status != scenario.status:
        result.problems.append(f"status {status} != {scenario.status}")
    if scenario.total is not None and (order is None or str(order.total) != scenario.total):
        result.problems.append(f"total {order and order.total} != {scenario.total}")
    if scenario.outcome is not None and outcome != scenario.outcome:
        result.problems.append(f"outcome {outcome} != {scenario.outcome}")
    if scenario.not_status is not None and status == scenario.not_status:
        result.problems.append(f"status must not be {status}")
    if scenario.no_items and order is not None and order.subtotal > 0:
        result.problems.append("added items the customer did not ask for")
    return result


def main(keys: set[str]) -> int:
    print(f"LLM: {settings.LLM_MODEL} at {settings.LLM_BASE_URL.split('/')[2]}")
    results = []
    with Session(engine) as session:
        business = eval_business(session)
        reset(session, business)
        for n, scenario in enumerate(SCENARIOS):
            if keys and scenario.key not in keys:
                continue
            results.append(run(scenario, session, business, f"90000000{n:02d}"))

    print("\n=== summary ===")
    for r in results:
        verdict = "PASS" if not r.problems else "FAIL: " + "; ".join(r.problems)
        avg = sum(r.seconds) / len(r.seconds)
        print(f"{r.scenario.key}. {r.scenario.title:32} {verdict}  (avg {avg:.1f}s/turn)")
    passed = sum(not r.problems for r in results)
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
