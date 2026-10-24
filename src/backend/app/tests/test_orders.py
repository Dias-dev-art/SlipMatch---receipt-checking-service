"""Order state machine via the owner API, timers, SSE events, tenancy."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlmodel import select

from app.models import Message, Order, OrderStatus, Sender
from app.models.base import utcnow
from app.services import events, timers
from app.services.outbox import CollectingOutbox, set_outbox
from app.tests.conftest import auth_headers, register
from app.tests.fake_llm import call, say, tools

PHONE = "60123456789"


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    client.post("/api/v1/menu", headers=headers, json={"name": "Nasi Lemak", "price": "8.00"})
    return headers


@pytest.fixture
def outbox():
    box = CollectingOutbox()
    set_outbox(box)
    yield box
    set_outbox(None)


def chat(client, headers, llm, *steps, text="msg", phone=PHONE):
    llm.script(*steps)
    r = client.post("/dev/simulate", headers=headers, json={"chat_id": phone, "text": text})
    assert r.status_code == 200, r.text
    return r.json()


def order_in(client, headers, llm, target: str, phone=PHONE) -> dict:
    """Drive a fresh order to `target` through the real pipeline."""
    body = chat(
        client,
        headers,
        llm,
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("ok"),
        text="2 nasi lemak tapau",
        phone=phone,
    )
    if target == "chatting":
        return body["order"]
    body = chat(
        client, headers, llm, tools(call("request_payment")), say("ok"), text="itu je", phone=phone
    )
    if target == "awaiting_payment":
        return body["order"]
    body = chat(
        client,
        headers,
        llm,
        tools(call("mark_paid_by_customer")),
        say("ok"),
        text="dah bayar",
        phone=phone,
    )
    assert body["order"]["status"] == "payment_check"
    return body["order"]


def post(client, headers, order, action, **json):
    return client.post(f"/api/v1/orders/{order['id']}/{action}", headers=headers, json=json or None)


# ---------------------------------------------------------------- allowed transitions


def test_approve_from_payment_check(client, owner, llm, outbox, session):
    order = order_in(client, owner, llm, "payment_check")
    r = post(client, owner, order, "approve")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["approved_at"] and body["expires_at"] is None
    assert outbox.sent[-1]["text"].startswith(f"Payment received, thank you! Order {order['code']}")
    assert outbox.sent[-1]["to"] == PHONE
    # the template is stored in the conversation too
    msgs = session.exec(select(Message).where(Message.sender == Sender.system)).all()
    assert any(m.body.startswith("Payment received") for m in msgs)


def test_double_approve_is_noop(client, owner, llm, outbox):
    order = order_in(client, owner, llm, "payment_check")
    post(client, owner, order, "approve")
    r = post(client, owner, order, "approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert len([m for m in outbox.sent if m["text"].startswith("Payment received")]) == 1


def test_not_received_restarts_timer(client, owner, llm, outbox, session):
    order = order_in(client, owner, llm, "payment_check")
    db_order = session.get(Order, uuid.UUID(order["id"]))
    db_order.expires_at = utcnow() + timedelta(seconds=5)
    session.add(db_order)
    session.commit()
    r = post(client, owner, order, "not-received")
    assert r.json()["status"] == "awaiting_payment"
    session.refresh(db_order)
    assert db_order.expires_at > utcnow() + timedelta(minutes=9)
    assert "don't see your payment" in outbox.sent[-1]["text"]
    # repeated click: no second message
    n = len(outbox.sent)
    assert post(client, owner, order, "not-received").status_code == 200
    assert len(outbox.sent) == n
    # the customer can say paid again
    body = chat(client, owner, llm, tools(call("mark_paid_by_customer")), say("ok"))
    assert body["order"]["status"] == "payment_check"


def test_restore_after_owner_timeout(client, owner, llm, outbox, session):
    order = order_in(client, owner, llm, "payment_check")
    db_order = session.get(Order, uuid.UUID(order["id"]))
    db_order.expires_at = utcnow() - timedelta(seconds=1)
    session.add(db_order)
    session.commit()
    assert timers.expire_due_orders() == 1
    r = client.get(f"/api/v1/orders/{order['id']}", headers=owner).json()
    assert r["status"] == "cancelled" and r["cancelled_reason"] == "owner_timeout"
    assert "could not confirm your payment" in outbox.sent[-1]["text"]

    r = post(client, owner, order, "restore")
    assert r.json()["status"] == "payment_check" and r.json()["cancelled_reason"] is None
    assert post(client, owner, order, "approve").json()["status"] == "approved"


def test_payment_timeout(client, owner, llm, outbox, session):
    order = order_in(client, owner, llm, "awaiting_payment")
    db_order = session.get(Order, uuid.UUID(order["id"]))
    db_order.expires_at = utcnow() - timedelta(seconds=1)
    session.add(db_order)
    session.commit()
    assert timers.expire_due_orders() == 1
    assert timers.expire_due_orders() == 0  # never twice
    session.refresh(db_order)
    assert db_order.status == OrderStatus.cancelled
    assert db_order.cancelled_reason == "payment_timeout"
    assert "did not receive the payment in time" in outbox.sent[-1]["text"]


def test_timer_ignores_orders_not_due(client, owner, llm):
    order_in(client, owner, llm, "awaiting_payment")
    assert timers.expire_due_orders() == 0


def test_owner_cancel(client, owner, llm, outbox, session):
    order = order_in(client, owner, llm, "awaiting_payment")
    r = post(client, owner, order, "cancel", reason="out of stock")
    assert r.json()["status"] == "cancelled" and r.json()["cancelled_reason"] == "owner_rejected"
    assert "cancelled by the shop" in outbox.sent[-1]["text"]
    note = session.exec(select(Message).where(Message.sender == Sender.system)).all()[-1]
    assert note.payload["owner_note"] == "out of stock"
    assert post(client, owner, order, "cancel", reason="again").status_code == 200  # no-op


def test_cancel_requires_reason(client, owner, llm):
    order = order_in(client, owner, llm, "chatting")
    assert post(client, owner, order, "cancel").status_code == 422


def test_new_order_after_approved(client, owner, llm):
    first = order_in(client, owner, llm, "payment_check")
    post(client, owner, first, "approve")
    second = order_in(client, owner, llm, "chatting")
    assert second["id"] != first["id"] and second["code"] != first["code"]


# ---------------------------------------------------------------- disallowed transitions


@pytest.mark.parametrize(
    ("state", "action"),
    [
        ("chatting", "approve"),
        ("awaiting_payment", "approve"),
        ("chatting", "not-received"),
        ("chatting", "restore"),
        ("awaiting_payment", "restore"),
        ("payment_check", "restore"),
    ],
)
def test_disallowed_transitions_return_409(client, owner, llm, outbox, state, action):
    order = order_in(client, owner, llm, state)
    r = post(client, owner, order, action)
    if (state, action) == ("payment_check", "restore"):
        assert r.status_code == 200  # already there: no-op
        return
    assert r.status_code == 409
    assert outbox.sent == []


def test_approved_cannot_be_cancelled_or_marked_not_received(client, owner, llm, outbox):
    order = order_in(client, owner, llm, "payment_check")
    post(client, owner, order, "approve")
    assert post(client, owner, order, "cancel", reason="x").status_code == 409
    assert post(client, owner, order, "not-received").status_code == 409
    assert post(client, owner, order, "restore").status_code == 409


def test_customer_cancelled_cannot_be_restored(client, owner, llm, session):
    order = order_in(client, owner, llm, "chatting")
    db_order = session.get(Order, uuid.UUID(order["id"]))
    db_order.status, db_order.cancelled_reason = OrderStatus.cancelled, "customer"
    session.add(db_order)
    session.commit()
    assert post(client, owner, order, "restore").status_code == 409


def test_restore_blocked_when_customer_has_new_open_order(client, owner, llm, outbox):
    order = order_in(client, owner, llm, "awaiting_payment")
    post(client, owner, order, "cancel", reason="mistake")
    order_in(client, owner, llm, "chatting")
    r = post(client, owner, order, "restore")
    assert r.status_code == 409 and "another open order" in r.json()["detail"]


# ---------------------------------------------------------------- listing and tenancy


def test_list_and_filter(client, owner, llm):
    a = order_in(client, owner, llm, "payment_check", phone="60111111111")
    b = order_in(client, owner, llm, "chatting", phone="60122222222")
    all_ = client.get("/api/v1/orders", headers=owner).json()
    assert [o["id"] for o in all_] == [b["id"], a["id"]]  # newest first
    checks = client.get("/api/v1/orders?status=payment_check", headers=owner).json()
    assert [o["id"] for o in checks] == [a["id"]]
    assert checks[0]["items"][0]["slug"] == "nasi_lemak"
    assert checks[0]["customer"]["phone"] == "60111111111"
    both = client.get("/api/v1/orders?status=payment_check&status=chatting", headers=owner).json()
    assert len(both) == 2


def test_owner_cannot_read_or_approve_other_business_orders(client, owner, llm, outbox):
    order = order_in(client, owner, llm, "payment_check")
    register(client, "teh@demo.my", "Mak Teh Bakery")
    other = auth_headers(client, "teh@demo.my")
    assert client.get("/api/v1/orders", headers=other).json() == []
    assert client.get(f"/api/v1/orders/{order['id']}", headers=other).status_code == 404
    for action in ("approve", "not-received", "restore"):
        assert post(client, other, order, action).status_code == 404
    assert post(client, other, order, "cancel", reason="x").status_code == 404
    assert client.get(f"/api/v1/orders/{order['id']}", headers=owner).json()["status"] == (
        "payment_check"
    )


def test_orders_require_auth(client):
    assert client.get("/api/v1/orders").status_code == 401


# ---------------------------------------------------------------- realtime


def test_events_endpoint_rejects_bad_token(client):
    assert client.get("/api/v1/events", params={"token": "garbage"}).status_code == 401
    assert client.get("/api/v1/events").status_code == 422


@pytest.fixture
def captured(monkeypatch):
    seen: list[tuple[str, dict]] = []
    real = events.bus.publish

    def spy(business_id, type_, **data):
        seen.append((type_, {k: str(v) for k, v in data.items()}))
        real(business_id, type_, **data)

    monkeypatch.setattr(events.bus, "publish", spy)
    return seen


def test_pipeline_and_owner_actions_publish_events(client, owner, llm, outbox, captured):
    order = order_in(client, owner, llm, "payment_check")
    types = [t for t, _ in captured]
    assert types[0] == "order.created"
    assert "order.updated" in types and "payment.check_requested" in types
    assert all(d.get("order_id") == order["id"] for _, d in captured)
    captured.clear()
    post(client, owner, order, "approve")
    assert captured == [("order.updated", {"order_id": order["id"]})]
    captured.clear()
    post(client, owner, order, "approve")  # no-op: no event
    assert captured == []


def test_handoff_publishes_needs_owner(client, owner, llm, captured):
    body = chat(client, owner, llm, tools(call("handoff_to_owner", reason="angry")))
    assert body["outcome"] == "handoff"
    assert [t for t, _ in captured] == ["conversation.needs_owner"]


def test_event_bus_delivers_per_business_and_streams_sse():
    async def scenario():
        mine, theirs = uuid.uuid4(), uuid.uuid4()
        sub = events.bus.subscribe(mine)
        gen = events.stream(sub, heartbeat=0.05)
        assert await gen.__anext__() == ": connected\n\n"
        assert await gen.__anext__() == ": ping\n\n"
        events.bus.publish(theirs, events.ORDER_UPDATED, order_id="other")
        events.bus.publish(mine, events.PAYMENT_CHECK_REQUESTED, order_id="o1")
        chunk = await gen.__anext__()
        await gen.aclose()
        assert sub not in events.bus._subs.get(mine, set())  # unsubscribed on disconnect
        return chunk

    chunk = asyncio.run(scenario())
    assert chunk == 'event: payment.check_requested\ndata: {"order_id": "o1"}\n\n'
