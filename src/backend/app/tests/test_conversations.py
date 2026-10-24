"""Handoff recovery (Resume AI, 24h auto-resume), AI pause, owner replies from the dashboard."""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.models import Conversation, Message
from app.models.base import utcnow
from app.services import timers
from app.services.outbox import CollectingOutbox, set_outbox
from app.tests.conftest import auth_headers, register
from app.tests.fake_llm import call, say, tools

PHONE = "60123456789"


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    client.post("/api/v1/menu", headers=headers, json={"name": "Teh Tarik", "price": "3.00"})
    return headers


def send(client, headers, text, phone=PHONE):
    r = client.post("/dev/simulate", headers=headers, json={"chat_id": phone, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def hand_off(client, owner, llm):
    llm.script(tools(call("handoff_to_owner", reason="refund")))
    assert send(client, owner, "nak refund")["outcome"] == "handoff"


def test_handed_off_chats_are_listed_with_history(client, owner, llm):
    llm.script(say("Hi!"))
    send(client, owner, "hello", phone="60111111111")  # a normal chat
    hand_off(client, owner, llm)
    flagged = client.get("/api/v1/conversations?needs_owner=true", headers=owner).json()
    assert len(flagged) == 1
    conv = flagged[0]
    assert conv["customer"]["phone"] == PHONE and conv["handoff_reason"] == "refund"
    assert conv["handoff_at"] and conv["last_message"].startswith("Thank you!")
    assert len(client.get("/api/v1/conversations", headers=owner).json()) == 2
    msgs = client.get(f"/api/v1/conversations/{conv['id']}/messages", headers=owner).json()
    assert [(m["direction"], m["body"]) for m in msgs][0] == ("in", "nak refund")


def test_resume_ai(client, owner, llm):
    hand_off(client, owner, llm)
    assert send(client, owner, "hello?")["outcome"] == "needs_owner"
    conv = client.get("/api/v1/conversations?needs_owner=true", headers=owner).json()[0]
    r = client.post(f"/api/v1/conversations/{conv['id']}/resume-ai", headers=owner)
    assert r.status_code == 200 and r.json()["needs_owner"] is False
    llm.script(say("Hi again!"))
    assert send(client, owner, "hello?")["reply"] == "Hi again!"


def test_fallback_can_be_resumed(client, owner, llm):
    llm.script(say('{"x":1}'), say('{"y":2}'))
    assert send(client, owner, "ok")["outcome"] == "fallback"
    conv = client.get("/api/v1/conversations?needs_owner=true", headers=owner).json()[0]
    assert conv["handoff_reason"] == "tool_text_in_reply" and conv["handoff_at"]
    client.post(f"/api/v1/conversations/{conv['id']}/resume-ai", headers=owner)
    llm.script(say("Sorry about that, what would you like?"))
    assert send(client, owner, "hello")["outcome"] == "reply"


def test_conversations_are_per_business(client, owner, llm):
    hand_off(client, owner, llm)
    conv = client.get("/api/v1/conversations", headers=owner).json()[0]
    register(client, "teh@demo.my", "Mak Teh Bakery")
    other = auth_headers(client, "teh@demo.my")
    assert client.get("/api/v1/conversations", headers=other).json() == []
    base = f"/api/v1/conversations/{conv['id']}"
    assert client.get(f"{base}/messages", headers=other).status_code == 404
    assert client.post(f"{base}/resume-ai", headers=other).status_code == 404


def test_handoff_auto_resumes_after_24h(client, owner, llm, session):
    hand_off(client, owner, llm)
    assert timers.resume_stale_handoffs() == 0  # too early
    conv = session.exec(select(Conversation)).one()
    conv.handoff_at = utcnow() - timedelta(hours=25)
    session.add(conv)
    session.commit()
    assert timers.resume_stale_handoffs() == 1
    session.refresh(conv)
    assert conv.needs_owner is False and conv.handoff_reason is None
    llm.script(say("Hi!"))
    assert send(client, owner, "hello")["outcome"] == "reply"


def test_paused_ai_stays_silent_until_the_pause_ends(client, owner, llm, session):
    llm.script(say("Hi!"))
    send(client, owner, "hello")
    conv = session.exec(select(Conversation)).one()
    conv.ai_paused_until = utcnow() + timedelta(hours=1)
    session.add(conv)
    session.commit()
    # the AI stays silent during the pause...
    assert send(client, owner, "thanks")["outcome"] == "ai_paused"
    # ...and answers again once it is over
    conv.ai_paused_until = utcnow() - timedelta(seconds=1)
    session.add(conv)
    session.commit()
    llm.script(say("Anything else?"))
    assert send(client, owner, "1 more teh tarik")["outcome"] == "reply"


@pytest.fixture
def sent():
    """What owner replies send to the customer's Telegram chat."""
    outbox = CollectingOutbox()
    set_outbox(outbox)
    yield outbox.sent
    set_outbox(None)


def test_owner_reply_goes_to_the_customer_signed_with_the_shop(client, owner, llm, sent, session):
    hand_off(client, owner, llm)
    conv = client.get("/api/v1/conversations?needs_owner=true", headers=owner).json()[0]
    r = client.post(
        f"/api/v1/conversations/{conv['id']}/reply",
        headers=owner,
        json={"text": "  So sorry! I have refunded RM3.  "},
    )
    assert r.status_code == 200, r.text
    assert sent == [
        {
            "type": "text",
            "to": PHONE,
            "text": "👩‍🍳 Kak Ani Kitchen:\nSo sorry! I have refunded RM3.",
        }
    ]
    body = r.json()
    assert body["needs_owner"] is False and body["ai_paused_until"] is not None
    owner_msg = session.exec(select(Message).where(Message.sender == "owner")).one()
    assert owner_msg.body.endswith("So sorry! I have refunded RM3.")
    # the owner has the chat now: the AI stays quiet until Resume AI
    assert send(client, owner, "ok thanks")["outcome"] == "ai_paused"
    client.post(f"/api/v1/conversations/{conv['id']}/resume-ai", headers=owner)
    llm.script(say("Anything else?"))
    assert send(client, owner, "1 teh tarik")["outcome"] == "reply"


def test_owner_reply_validation_and_tenancy(client, owner, llm, sent):
    hand_off(client, owner, llm)
    conv = client.get("/api/v1/conversations?needs_owner=true", headers=owner).json()[0]
    url = f"/api/v1/conversations/{conv['id']}/reply"
    assert client.post(url, headers=owner, json={"text": "   "}).status_code == 422
    assert client.post(url, headers=owner, json={"text": ""}).status_code == 422
    register(client, "teh@demo.my", "Mak Teh Bakery")
    other = auth_headers(client, "teh@demo.my")
    assert client.post(url, headers=other, json={"text": "hi"}).status_code == 404
    assert sent == []


def test_owner_pause_is_short_and_ends_by_itself(client, owner, llm, sent, session):
    """Seen live: after the owner replied and left, the AI ignored the customer for 24 hours."""
    hand_off(client, owner, llm)
    conv = client.get("/api/v1/conversations?needs_owner=true", headers=owner).json()[0]
    client.post(f"/api/v1/conversations/{conv['id']}/reply", headers=owner, json={"text": "Hi!"})
    paused = session.exec(select(Conversation)).one()
    assert paused.ai_paused_until < utcnow() + timedelta(minutes=16)
    # 15 minutes after the owner's last reply, the AI answers again
    paused.ai_paused_until = utcnow() - timedelta(seconds=1)
    session.add(paused)
    session.commit()
    llm.script(say("Anything else?"))
    assert send(client, owner, "1 teh tarik")["outcome"] == "reply"
