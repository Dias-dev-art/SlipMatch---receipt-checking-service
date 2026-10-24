"""Agent loop + pipeline through POST /dev/simulate with a scripted LLM (no network)."""

import json
import re
from pathlib import Path

import pytest
from sqlmodel import col, select

from app.agent.loop import invalid_reply
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
    # both order types, so the customer has to choose (pickup-only shops are tested separately)
    client.patch("/api/v1/business", headers=headers, json={"delivery_enabled": True})
    return headers


def send(client, headers, text, phone=PHONE):
    r = client.post("/dev/simulate", headers=headers, json={"chat_id": phone, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_tools_match_api_md():
    block = re.search(
        r"## AI tools.*?```json\n(.*?)```", API_MD.read_text(encoding="utf-8"), re.S
    ).group(1)
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
    # the AI's opener, then the real cart and the next question, written by code
    assert body["reply"] == (
        "Ok boss, 2 nasi lemak tapau.\n\nYour order:\n• 2× Nasi Lemak – RM16.00\n"
        "Total: RM16.00\n\nAnything else, or shall I send the payment details?"
    )
    assert body["order"]["status"] == "chatting"
    assert body["order"]["total"] == "16.00"
    assert [(i["slug"], i["qty"]) for i in body["order"]["items"]] == [("nasi_lemak", 2)]
    assert body["sent"] == [{"type": "text", "to": PHONE, "text": body["reply"]}]

    # the LLM saw the tool results computed by Python
    results = llm.tool_results()
    # "tapau": code set pickup first, then the model's add_item ran
    assert results[0]["order_type"] == "pickup"
    assert any(r.get("total") == 16.0 for r in results) and results[-1]["missing_fields"] == []

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


def test_request_payment_written_as_text_waits_for_the_customer(client, owner, llm, session):
    """The model wrote "request_payment" as text, but the customer never said they were done."""
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("ok"),
    )
    send(client, owner, "2 nasi lemak tapau")
    llm.script(say("request_payment"), say("Anything else?"))
    body = send(client, owner, "hmm ok la")
    assert body["order"]["status"] == "chatting" and body["reply"] == "Anything else?"
    assert "request_payment" not in json.dumps(body["sent"])
    # the model saw why: it was run through the normal path and refused by code
    assert llm.tool_results()[0]["error"] == "customer_not_done"
    ai = session.exec(
        select(Message).where(Message.sender == "ai").order_by(col(Message.created_at).desc())
    ).first()
    assert any(step.get("recovered_text_tool") == "request_payment" for step in ai.payload["trace"])


@pytest.mark.parametrize(
    ("tool", "args", "text"),
    [
        ("set_order_type", {"type": "pickup"}, "one nasi lemak"),
        ("request_payment", {}, "one nasi lemak"),
    ],
)
def test_model_cannot_choose_for_the_customer(client, owner, llm, tool, args, text):
    """Seen live: after "one nasi lemak" the model chose pickup and sent the QR by itself."""
    llm.script(
        tools(call("add_item", menu_item_id="nasi_lemak", qty=1), call(tool, **args)),
        say("Pickup or delivery?"),
    )
    body = send(client, owner, text)
    assert body["order"]["status"] == "chatting" and body["order"]["order_type"] is None
    assert not any(m["text"].startswith("Pay ") for m in body["sent"] if m["type"] == "text")


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
    # either the bad sentences were dropped or the model was asked again; never the claim
    assert body["reply"] and invalid_reply(body["reply"]) is None
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


# ---------------------------------------------------------------- code-decided steps


def pickup_cart(client, owner, llm):
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("Ok boss. Anything else?"),
    )
    send(client, owner, "2 nasi lemak tapau")


@pytest.mark.parametrize("text", ["itu je", "No thats all", "Give the qr then", "nak bayar"])
def test_checkout_phrase_sends_payment_even_if_the_model_only_chats(client, owner, llm, text):
    pickup_cart(client, owner, llm)
    llm.script(say("Thank you boss!"))
    body = send(client, owner, text)
    code = body["order"]["code"]
    assert body["order"]["status"] == "awaiting_payment"
    assert body["sent"][0]["text"].startswith(f"Pay RM16.00, reference {code}")
    assert body["sent"][-1]["text"] == "Thank you boss!"
    assert llm.tool_results()[0]["payment_sent"] is True  # the model saw it happen


def test_short_no_after_anything_else_is_checkout(client, owner, llm):
    pickup_cart(client, owner, llm)  # the AI asked "Anything else?"
    llm.script(say("Thanks!"))
    assert send(client, owner, "no")["order"]["status"] == "awaiting_payment"


def test_checkout_phrase_with_incomplete_cart_is_left_to_the_model(client, owner, llm):
    llm.script(
        tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("Pickup or delivery?")
    )
    send(client, owner, "1 nasi lemak")
    llm.script(say("Pickup or delivery?"))
    body = send(client, owner, "itu je")
    assert body["order"]["status"] == "chatting" and body["reply"] == "Pickup or delivery?"


def test_paid_phrase_and_qr_request_while_awaiting_payment(client, owner, llm):
    pickup_cart(client, owner, llm)
    llm.script(say("Thanks!"))
    send(client, owner, "itu je")
    # "you did not send it": code sends the payment details again
    llm.script(say("Sent again!"))
    body = send(client, owner, "You did not send the qr")
    assert body["sent"][0]["text"].startswith("Pay RM16.00")
    assert body["order"]["status"] == "awaiting_payment"
    # "dah bayar" moves it to the owner's Check payment column without the model calling a tool
    llm.script(say("Thanks, the owner will check it."))
    body = send(client, owner, "dah bayar")
    assert body["order"]["status"] == "payment_check"


def test_items_the_model_only_talked_about_are_added_by_code(client, owner, llm):
    """Seen live: "can I also add one mee goreng and 2 teh tarik" got no add_item call."""
    pickup_cart(client, owner, llm)
    llm.script(say("Great choice! One Mee Goreng and two Teh Tarik are added to your order."))
    body = send(client, owner, "can I also add one mee gorend and 2 teh tarik")
    items = {i["slug"]: i["qty"] for i in body["order"]["items"]}
    assert items == {"nasi_lemak": 2, "mee_goreng": 1, "teh_tarik": 2}
    assert body["order"]["total"] == "29.00"
    assert body["reply"] == (
        "Great choice!\n\nYour order:\n• 1× Mee Goreng – RM7.00\n• 2× Nasi Lemak – RM16.00\n"
        "• 2× Teh Tarik – RM6.00\nTotal: RM29.00\n\n"
        "Anything else, or shall I send the payment details?"
    )
    assert len(llm.requests) == 3  # 2 for the first cart, 1 here: no extra round for a correction


def test_claimed_cart_change_without_tool_is_corrected(client, owner, llm):
    # nothing on the menu in the customer's words, so the model is asked to use the tools
    llm.script(
        say("Sure thing! Adding one Teh Tarik to your order."),
        tools(call("add_item", menu_item_id="teh_tarik", qty=1)),
        say("Done!"),
    )
    body = send(client, owner, "the usual drink please")
    assert body["reply"].startswith("Done!\n\nYour order:\n• 1× Teh Tarik – RM3.00")
    assert "Adding one" not in json.dumps(body["sent"])


def test_model_that_keeps_pretending_gets_a_fixed_question(client, owner, llm, session):
    llm.script(say("Adding one Teh Tarik."), say("Your total is RM3.00, here is the QR."))
    body = send(client, owner, "the usual please")
    assert body["reply"] == "Sorry, I didn't catch that. Which items would you like, and how many?"
    assert session.exec(select(Conversation)).one().needs_owner is False  # chat stays with the AI


def test_cart_lie_after_a_real_tool_call_is_replaced_by_the_real_cart(client, owner, llm):
    """Seen live: set_order_type ran, then "One Besh and one Mee Goreng are added" (only Besh)."""
    llm.script(tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("Sure!"))
    send(client, owner, "one nasi lemak")
    llm.script(
        tools(call("set_order_type", type="pickup")),
        say("Great! One Nasi Lemak and one Mee Goreng are added to your order. Total RM15.00."),
    )
    body = send(client, owner, "pickup")
    assert body["reply"] == (
        "Great!\n\nYour order:\n• 1× Nasi Lemak – RM8.00\nTotal: RM8.00\n\n"
        "Anything else, or shall I send the payment details?"
    )


def test_quoting_the_real_total_without_a_tool_is_fine(client, owner, llm):
    pickup_cart(client, owner, llm)
    llm.script(say("Your total is RM16.00 for 2 Nasi Lemak."))
    assert send(client, owner, "how much ah")["reply"] == "Your total is RM16.00 for 2 Nasi Lemak."


@pytest.mark.parametrize("bad", ["Your order is on its way!", "Enjoy your meal!"])
def test_order_status_claims_are_blocked(client, owner, llm, bad):
    llm.script(say(bad), say("The owner will confirm your order soon."))
    assert send(client, owner, "ok")["reply"] == "The owner will confirm your order soon."


def test_tool_calls_written_as_text_are_run(client, owner, llm):
    written = (
        '<tool_call>\n{"name": "add_item", "arguments": {"menu_item_id": "mee_goreng", "qty": 1}}\n'
        '<tool_call>\n{"name": "add_item", "arguments": {"menu_item_id": "teh_tarik", "qty": 1}}'
    )
    llm.script(say(written), say("Mee Goreng and Teh Tarik added. Pickup or delivery?"))
    body = send(client, owner, "1 mee goreng 1 teh tarik")
    assert body["order"]["total"] == "10.00"
    assert body["reply"].endswith("Total: RM10.00\n\nPickup or delivery?")
    assert "tool_call" not in json.dumps(body["sent"])


def test_status_claim_sentence_is_dropped_from_a_good_reply(client, owner, llm):
    llm.script(say("Thanks, the owner will check the payment. Your order is on the way!"))
    assert send(client, owner, "ok")["reply"] == "Thanks, the owner will check the payment."


def test_offer_to_add_is_not_a_claim(client, owner, llm):
    llm.script(say("Mee Goreng is a bit spicy and has egg. Shall I add one for you?"))
    body = send(client, owner, "mee goreng pedas tak?")
    assert body["reply"] == "Mee Goreng is a bit spicy and has egg. Shall I add one for you?"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("can I also add one mee goreng and 2 teh tarik", [("mee_goreng", 1), ("teh_tarik", 2)]),
        ("nak dua nasi lemak", [("nasi_lemak", 2)]),
        ("1 mee gorend pls", [("mee_goreng", 1)]),
        ("teh tarik x3", [("teh_tarik", 3)]),
        ("NASI LEMAK", [("nasi_lemak", 1)]),
        ("ada pizza tak", []),
    ],
)
def test_parse_items(text, expected):
    from app.agent.intents import parse_items
    from app.models import MenuItem

    menu = [
        MenuItem(slug="nasi_lemak", name="Nasi Lemak", price=8),
        MenuItem(slug="mee_goreng", name="Mee Goreng", price=7),
        MenuItem(slug="teh_tarik", name="Teh Tarik", price=3),
    ]
    assert sorted(parse_items(text, menu)) == sorted(expected)


def test_yes_after_the_summary_question_sends_the_payment(client, owner, llm):
    pickup_cart(client, owner, llm)  # the summary ends with "shall I send the payment details?"
    llm.script(say("Thank you!"))
    assert send(client, owner, "boleh")["order"]["status"] == "awaiting_payment"


def test_copied_cart_summary_without_a_tool_is_not_trusted(client, owner, llm):
    """Seen live: the model typed its own "Your order: ... Total" block and called no tool."""
    llm.script(tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("Sure!"))
    send(client, owner, "one nasi lemak")
    fake = (
        "Sure thing! Your order:\n• 1× Nasi Lemak – RM8.00\n• 1× Mee Goreng – RM7.00\n"
        "Total: RM15.00\nPickup or delivery?"
    )
    llm.script(say(fake))
    body = send(client, owner, "can I also add one mee goreng")
    # code read the item from the customer's words and wrote the real summary
    assert {i["slug"]: i["qty"] for i in body["order"]["items"]} == {
        "nasi_lemak": 1,
        "mee_goreng": 1,
    }
    assert body["reply"].endswith("Total: RM15.00\n\nPickup or delivery?")
    assert body["reply"].startswith("Sure thing!\n\nYour order:")


# ---------------------------------------------------------------- menu, owner, order types


@pytest.mark.parametrize("menu", [[], [("Burger", "10.00")]])
def test_menu_question_is_answered_from_the_real_menu(client, llm, menu):
    """Seen live: for a 1-item menu the model listed Fries, Nuggets, Coke and Sprite."""
    register(client, "kang@demo.my", "Burger Kang")
    headers = auth_headers(client, "kang@demo.my")
    for name, price in menu:
        client.post("/api/v1/menu", headers=headers, json={"name": name, "price": price})
    body = send(client, headers, "Whats the menu?")
    expected = (
        "Menu:\n• Burger – RM10.00\n\nWhat would you like?"
        if menu
        else "Sorry, nothing is available to order right now. Please check again later."
    )
    assert body["reply"] == expected
    assert llm.requests == []  # no model involved


def test_asking_for_the_owner_hands_off_by_code(client, owner, llm, session):
    """Seen live: "Can you pass me to the owner" got "Handing over..." text and no handoff."""
    body = send(client, owner, "Can you pass me to the owner")
    assert body["outcome"] == "handoff" and "owner" in body["reply"]
    conv = session.exec(select(Conversation)).one()
    assert conv.needs_owner and "owner" in conv.handoff_reason
    assert llm.requests == []


def test_disabled_order_type_is_refused_by_code(client, owner, llm):
    """Seen live: "Delivery" was accepted although the shop had delivery switched off."""
    client.patch(
        "/api/v1/business", headers=owner, json={"delivery_enabled": False, "pickup_enabled": True}
    )
    llm.script(tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("Sure!"))
    body = send(client, owner, "one nasi lemak")
    # pickup is the only option, so code set it: no "pickup or delivery?" question
    assert body["order"]["order_type"] == "pickup"
    assert body["reply"].endswith("Anything else, or shall I send the payment details?")
    body = send(client, owner, "Delivery")
    assert body["reply"].startswith(
        "Sorry, Kak Ani Kitchen doesn't do delivery right now, only pickup."
    )
    assert body["order"]["order_type"] == "pickup"


def test_customer_choice_of_order_type_is_set_by_code(client, owner, llm):
    llm.script(tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("Sure!"))
    send(client, owner, "one nasi lemak")
    llm.script(say("Where should we deliver?"))  # the model forgets set_order_type
    body = send(client, owner, "delivery please")
    assert body["order"]["order_type"] == "delivery"
    assert body["reply"].endswith("What's the delivery address?")
