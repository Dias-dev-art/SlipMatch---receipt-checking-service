"""Agent loop + pipeline through POST /dev/simulate with a scripted LLM (no network)."""

import json
import re
from pathlib import Path

import pytest
from sqlmodel import select

from app.agent.tools import TOOLS
from app.models import Conversation, Message
from app.tests.conftest import auth_headers, register
from app.tests.fake_llm import LLMError, call, say, tools

API_MD = Path(__file__).resolve().parents[3] / "API.md"
PHONE = "60123456789"


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    for name, price in [("Nasi Lemak", "8.00"), ("Teh Tarik", "3.00"), ("Mee Goreng", "7.00")]:
        client.post("/api/v1/menu", headers=headers, json={"name": name, "price": price})
    return headers


def send(client, headers, text, phone=PHONE):
    r = client.post("/dev/simulate", headers=headers, json={"customer_phone": phone, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_tools_match_api_md():
    block = re.search(r"## AI tools.*?```json\n(.*?)```", API_MD.read_text(), re.S).group(1)
    assert json.loads(block) == TOOLS


def test_full_order_flow(client, owner, llm):
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("Ok boss, 2 nasi lemak tapau. Anything else?"),
    )
    body = send(client, owner, "boss nak 2 nasi lemak tapau")
    assert body["outcome"] == "reply"
    assert body["reply"] == "Ok boss, 2 nasi lemak tapau. Anything else?"
    assert body["order"]["status"] == "chatting"
    assert body["order"]["total"] == "16.00"
    assert [(i["slug"], i["qty"]) for i in body["order"]["items"]] == [("nasi_lemak", 2)]
    assert body["sent"] == [{"type": "text", "to": PHONE, "text": body["reply"]}]

    # the LLM saw the tool results computed by Python
    results = llm.tool_results()
    assert results[0]["total"] == 16.0 and results[1]["missing_fields"] == []

    llm.script(tools(call("request_payment")), say("Thank you!"))
    body = send(client, owner, "itu je")
    code = body["order"]["code"]
    assert body["order"]["status"] == "awaiting_payment"
    assert body["sent"][0]["text"].startswith(f"Pay RM16.00, reference {code}")
    assert body["sent"][-1] == {"type": "text", "to": PHONE, "text": "Thank you!"}

    llm.script(tools(call("mark_paid_by_customer")), say("Thanks, we are checking."))
    body = send(client, owner, "dah bayar")
    assert body["order"]["status"] == "payment_check"


def test_system_prompt_has_only_available_items_and_current_cart(client, owner, llm):
    items = client.get("/api/v1/menu", headers=owner).json()
    mee = next(i for i in items if i["slug"] == "mee_goreng")
    client.patch(
        f"/api/v1/menu/{mee['id']}/availability", headers=owner, json={"is_available": False}
    )
    llm.script(tools(call("add_item", menu_item_id="teh_tarik", qty=1)), say("ok"))
    send(client, owner, "1 teh tarik")
    first, second = llm.requests[0][0]["content"], llm.requests[1][0]["content"]
    assert '"id":"nasi_lemak"' in first and '"id":"mee_goreng"' not in first
    assert '"cart":[]' in first
    # refreshed after the tool call
    assert '"cart":[{"id":"teh_tarik"' in second
    assert llm.tools_seen[0] == TOOLS


def test_history_is_sent(client, owner, llm):
    llm.script(say("Hi! What would you like?"))
    send(client, owner, "hello")
    llm.script(say("Sure"))
    send(client, owner, "1 teh tarik")
    roles = [(m["role"], m["content"]) for m in llm.requests[-1][1:]]
    assert roles == [
        ("user", "hello"),
        ("assistant", "Hi! What would you like?"),
        ("user", "1 teh tarik"),
    ]


def test_handoff_then_ai_is_silent(client, owner, llm, session):
    llm.script(tools(call("handoff_to_owner", reason="refund request")))
    body = send(client, owner, "I want a refund!!")
    assert body["outcome"] == "handoff"
    assert "owner" in body["reply"]
    conv = session.exec(select(Conversation)).one()
    assert conv.needs_owner and conv.handoff_reason == "refund request"

    body = send(client, owner, "hello??")
    assert body["outcome"] == "needs_owner" and body["reply"] is None and body["sent"] == []
    assert llm.steps == []  # LLM not called


def test_ignore_or_flag_sends_nothing(client, owner, llm):
    llm.script(tools(call("ignore_or_flag", reason="friend chat")))
    body = send(client, owner, "bro jom lepak mamak")
    assert body["outcome"] == "ignored" and body["reply"] is None and body["sent"] == []


def test_llm_error_gives_fallback_and_flags_owner(client, owner, llm, session):
    llm.script(LLMError("timeout"))
    body = send(client, owner, "1 nasi lemak")
    assert body["outcome"] == "fallback"
    assert "owner" in body["reply"]
    assert session.exec(select(Conversation)).one().needs_owner


def test_iteration_limit_gives_fallback(client, owner, llm):
    llm.script(*[tools(call("add_item", menu_item_id="teh_tarik", qty=1)) for _ in range(6)])
    body = send(client, owner, "teh tarik")
    assert body["outcome"] == "fallback"


def test_error_results_go_back_to_llm(client, owner, llm):
    llm.script(
        tools(call("add_item", menu_item_id="nasi_ayam", qty=1)),
        say("Sorry, no nasi ayam. We have Nasi Lemak."),
    )
    body = send(client, owner, "ada nasi ayam?")
    assert llm.tool_results()[0]["error"] == "not_on_menu"
    assert body["order"] is None  # nothing valid was added, so no order was created


def test_agent_turn_logged_in_messages(client, owner, llm, session):
    llm.script(tools(call("add_item", menu_item_id="teh_tarik", qty=1)), say("ok"))
    send(client, owner, "1 teh tarik")
    ai = session.exec(select(Message).where(Message.sender == "ai")).one()
    assert ai.payload["outcome"] == "reply"
    assert ai.payload["trace"][0]["tool"] == "add_item"


def test_customers_are_separate_conversations(client, owner, llm):
    llm.script(tools(call("add_item", menu_item_id="teh_tarik", qty=1)), say("ok"), say("hi"))
    a = send(client, owner, "1 teh tarik", phone="60111111111")
    b = send(client, owner, "hi", phone="60122222222")
    assert a["order"]["total"] == "3.00"
    assert b["order"] is None


def test_simulate_uses_own_business(client, owner, llm):
    register(client, "teh@demo.my", "Mak Teh Bakery")
    other = auth_headers(client, "teh@demo.my")
    llm.script(tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("no such item"))
    body = send(client, other, "1 nasi lemak")
    # Mak Teh has no menu: Kak Ani's items are not visible
    assert llm.tool_results()[0]["error"] == "not_on_menu"
    assert '"id":"nasi_lemak"' not in llm.requests[0][0]["content"]
    assert body["order"] is None or body["order"]["items"] == []


def test_reset(client, owner, llm, session):
    llm.script(say("hi"))
    send(client, owner, "hello")
    assert client.post("/dev/reset", headers=owner).status_code == 204
    assert session.exec(select(Message)).all() == []


def test_menu_delete_is_soft_when_ordered(client, owner, llm):
    llm.script(tools(call("add_item", menu_item_id="teh_tarik", qty=1)), say("ok"))
    body = send(client, owner, "1 teh tarik")
    item_id = body["order"]["items"][0]["menu_item_id"]
    assert client.delete(f"/api/v1/menu/{item_id}", headers=owner).status_code == 204
    assert all(i["slug"] != "teh_tarik" for i in client.get("/api/v1/menu", headers=owner).json())
    # the order still shows it
    llm.script(say("ok"))
    assert send(client, owner, "status?")["order"]["items"][0]["slug"] == "teh_tarik"


def test_tool_name_inside_text_is_not_sent(client, owner, llm):
    llm.script(say("I will call add_item for you"), say("Sure, one teh tarik?"))
    body = send(client, owner, "ok itu je")
    assert body["reply"] == "Sure, one teh tarik?"
    assert "add_item" not in json.dumps(body["sent"])
    assert llm.requests[1][-1]["role"] == "system"  # the correction


def test_repeated_tool_text_falls_back(client, owner, llm):
    llm.script(say('{"items": []}'), say('{"cart": []}'))
    body = send(client, owner, "ok")
    assert body["outcome"] == "fallback"


def test_request_payment_written_as_text_is_run(client, owner, llm, session):
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("ok"),
    )
    send(client, owner, "2 nasi lemak tapau")
    llm.script(say("request_payment"), say("Thank you!"))
    body = send(client, owner, "itu je")
    code = body["order"]["code"]
    assert body["outcome"] == "reply" and body["order"]["status"] == "awaiting_payment"
    assert body["sent"][0]["text"].startswith(f"Pay RM16.00, reference {code}")
    assert body["sent"][-1]["text"] == "Thank you!"
    assert "request_payment" not in json.dumps(body["sent"])
    # the LLM saw the result as a normal tool result
    assert llm.tool_results()[0]["payment_sent"] is True
    ai = session.exec(select(Message).where(Message.sender == "ai")).all()[-1]
    assert ai.payload["trace"][1]["recovered_text_tool"] == "request_payment"


def test_mark_paid_written_as_text_without_payment_request(client, owner, llm):
    llm.script(say("`mark_paid_by_customer`"), say("Please order first."))
    body = send(client, owner, "dah bayar")
    assert body["reply"] == "Please order first."
    assert llm.tool_results()[0] == {"error": "no_payment_requested"}


def test_text_tool_is_recovered_only_once(client, owner, llm):
    llm.script(say("request_payment"), say("request_payment"), say("request_payment"))
    body = send(client, owner, "ok")
    assert body["outcome"] == "fallback"
    assert "request_payment" not in json.dumps(body["sent"])


@pytest.mark.parametrize(
    ("status_setup", "hint"),
    [
        ([], "Still missing: items, order_type."),
        (["add", "pickup"], "call request_payment"),
        (["add", "pickup", "pay"], "call mark_paid_by_customer"),
    ],
)
def test_prompt_next_step_hint(client, owner, llm, status_setup, hint):
    steps = {
        "add": call("add_item", menu_item_id="teh_tarik", qty=1),
        "pickup": call("set_order_type", type="pickup"),
        "pay": call("request_payment"),
    }
    if status_setup:
        llm.script(tools(*[steps[s] for s in status_setup]), say("ok"))
        send(client, owner, "setup")
    llm.script(say("ok"))
    send(client, owner, "next")
    assert hint in llm.requests[-1][0]["content"]


@pytest.mark.parametrize(
    "bad",
    [
        "Marked as paid by customer. Thanks!",
        "Terima kasih atas pembayarannya!",
        "Your payment has been received.",
        "Pembayaran anda telah diterima",
        "Total RM15 <|im_start|><|im_start|>",
        # seen live with the RunPod model
        "Marked your order as paid. Your meal will be delivered soon. Enjoy your meal!",
        "Your order is now paid, thank you!",
        "Your payment was successful.",
        "Marking as paid by customer. Terima kasih! Apa lagi adik nak?",
        "Sudah, order anda kami markas sebagai sudah bayar. Terima kasih!",
        "Pesanan anda sudah dibayar.",
        "Saya sudah mendaftar pembayaran anda. Terima kasih!",
        '/ionorf {"reason": "not related to ordering"}',
    ],
)
def test_bad_replies_are_never_sent(client, owner, llm, bad):
    llm.script(say(bad), say("Thanks, the owner will check the payment soon."))
    body = send(client, owner, "dah bayar")
    assert body["reply"] == "Thanks, the owner will check the payment soon."
    assert bad not in json.dumps(body["sent"], ensure_ascii=False)


@pytest.mark.parametrize(
    "ok",
    [
        "Please make the payment and tell us when done.",
        "Once the payment is done, let me know.",
        "Kalau sudah bayar, beritahu kami ya.",
        "Bila dah bayar, beritahu kami. Owner akan semak.",
        "Sila buat pembayaran anda dalam 10 minit.",
        "Your order is set for pickup. Ready to pay?",
    ],
)
def test_normal_reply_mentioning_payment_is_allowed(client, owner, llm, ok):
    llm.script(say(ok))
    assert send(client, owner, "how to pay?")["outcome"] == "reply"
