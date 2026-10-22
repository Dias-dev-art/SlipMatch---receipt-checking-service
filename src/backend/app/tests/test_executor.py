from decimal import Decimal

import pytest
from sqlmodel import select

from app.agent.executor import ToolContext, execute_tool
from app.models import Conversation, Customer, MenuItem, OrderStatus
from app.seed import seed


@pytest.fixture
def ctx(session):
    business = seed(session)
    customer = Customer(business_id=business.id, wa_phone="60123456789")
    session.add(customer)
    session.flush()
    conversation = Conversation(business_id=business.id, customer_id=customer.id)
    session.add(conversation)
    session.flush()
    sent: list[tuple] = []
    c = ToolContext(
        session,
        business,
        conversation,
        send_text=lambda text: sent.append(("text", text)),
        send_image=lambda url, caption: sent.append(("image", url)),
    )
    c.sent = sent  # type: ignore[attr-defined]
    return c


def run(ctx, name, **args):
    return execute_tool(ctx, name, args)


def test_add_valid_item_uses_db_price(ctx):
    r = run(ctx, "add_item", menu_item_id="nasi_lemak", qty=2)
    assert r["ok"] is True
    assert r["cart"] == [{"id": "nasi_lemak", "name": "Nasi Lemak", "qty": 2, "unit_price": 8.0}]
    assert r["subtotal"] == 16.0 and r["total"] == 16.0
    assert r["missing_fields"] == ["order_type"]


def test_add_same_item_merges_and_note_splits(ctx):
    run(ctx, "add_item", menu_item_id="mee_goreng", qty=1)
    run(ctx, "add_item", menu_item_id="mee_goreng", qty=2)
    r = run(ctx, "add_item", menu_item_id="mee_goreng", qty=1, note="less spicy")
    assert [(c["qty"], c.get("note")) for c in r["cart"]] == [(3, None), (1, "less spicy")]
    assert r["total"] == 28.0


def test_add_unknown_item(ctx):
    r = run(ctx, "add_item", menu_item_id="nasi_lemakk", qty=1)
    assert r["error"] == "not_on_menu"
    assert r["item"] == "nasi_lemakk"
    assert "nasi_lemak" in r["suggestions"]


def test_add_sold_out_item(ctx, session):
    item = session.exec(select(MenuItem).where(MenuItem.slug == "mee_goreng")).one()
    item.is_available = False
    session.add(item)
    assert run(ctx, "add_item", menu_item_id="mee_goreng", qty=1) == {
        "error": "sold_out",
        "item": "mee_goreng",
    }


def test_deleted_item_is_not_on_menu(ctx, session):
    from app.models.base import utcnow

    item = session.exec(select(MenuItem).where(MenuItem.slug == "teh_tarik")).one()
    item.deleted_at = utcnow()
    session.add(item)
    assert run(ctx, "add_item", menu_item_id="teh_tarik", qty=1)["error"] == "not_on_menu"


@pytest.mark.parametrize("qty", [0, -1, 1.5, "two", None, True])
def test_bad_qty(ctx, qty):
    assert run(ctx, "add_item", menu_item_id="nasi_lemak", qty=qty)["error"] == "invalid_arguments"


def test_qty_cap(ctx):
    assert run(ctx, "add_item", menu_item_id="nasi_lemak", qty=500)["error"] == "qty_too_large"


def test_llm_numbers_are_ignored(ctx):
    r = run(ctx, "add_item", menu_item_id="roti_canai", qty=3, price=0.01, total=0)
    assert r["total"] == 6.0


def test_invalid_json_and_unknown_tool(ctx):
    assert execute_tool(ctx, "add_item", "{not json")["error"] == "invalid_arguments"
    assert execute_tool(ctx, "give_discount", "{}")["error"] == "unknown_tool"


def test_totals_with_delivery_fee(ctx):
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=1)
    run(ctx, "add_item", menu_item_id="teh_tarik", qty=1)
    r = run(ctx, "set_order_type", type="delivery")
    assert r["subtotal"] == 11.0 and r["delivery_fee"] == 3.0 and r["total"] == 14.0
    assert r["missing_fields"] == ["address"]
    r = run(ctx, "set_order_type", type="pickup")
    assert r["total"] == 11.0 and "delivery_fee" not in r


def test_delivery_disabled(ctx):
    ctx.business.delivery_enabled = False
    assert run(ctx, "set_order_type", type="delivery") == {"error": "delivery_not_available"}
    assert run(ctx, "set_order_type", type="drone")["error"] == "invalid_arguments"


def test_remove_item(ctx):
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=3)
    r = run(ctx, "remove_item", menu_item_id="nasi_lemak", qty=1)
    assert r["cart"][0]["qty"] == 2 and r["total"] == 16.0
    r = run(ctx, "remove_item", menu_item_id="nasi_lemak")
    assert r["cart"] == [] and r["total"] == 0.0
    assert run(ctx, "remove_item", menu_item_id="teh_tarik")["error"] == "not_in_cart"


def test_remove_without_order(ctx):
    assert run(ctx, "remove_item", menu_item_id="nasi_lemak") == {"error": "no_active_order"}


def test_request_payment_missing_fields(ctx):
    assert run(ctx, "request_payment") == {
        "error": "missing_fields",
        "fields": ["items", "order_type"],
    }
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=1)
    run(ctx, "set_order_type", type="delivery")
    assert run(ctx, "request_payment") == {"error": "missing_fields", "fields": ["address"]}
    assert ctx.order.status == OrderStatus.chatting
    assert ctx.sent == []


def test_request_payment_freezes_total_and_sends_once(ctx):
    ctx.business.payment_qr_url = "https://example.com/qr.png"
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=1)
    run(ctx, "set_order_type", type="delivery")
    run(ctx, "set_address", address="  12 Jalan Bunga,   Taman Melati ")
    r = run(ctx, "request_payment")
    assert r["ok"] and r["status"] == "awaiting_payment" and r["payment_sent"] is True
    assert r["total"] == 11.0
    order = ctx.order
    assert order.address_text == "12 Jalan Bunga, Taman Melati"
    assert order.expires_at is not None
    assert ctx.sent[0] == ("image", "https://example.com/qr.png")
    assert ctx.sent[1][1].startswith(f"Pay RM11.00, reference {order.code}")
    again = run(ctx, "request_payment")
    assert again["payment_sent"] is False and len(ctx.sent) == 2


def test_unique_amount_cents(ctx):
    ctx.business.unique_amount_cents = True
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=1)
    run(ctx, "set_order_type", type="pickup")
    total = Decimal(str(run(ctx, "request_payment")["total"]))
    assert Decimal("8.01") <= total <= Decimal("8.99")


def test_changing_cart_after_payment_request_reopens(ctx):
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=1)
    run(ctx, "set_order_type", type="pickup")
    run(ctx, "request_payment")
    r = run(ctx, "add_item", menu_item_id="teh_tarik", qty=1)
    assert r["payment_request_cancelled"] is True and r["total"] == 11.0
    order = ctx.order
    assert order.status == OrderStatus.chatting and order.expires_at is None


def test_mark_paid(ctx):
    assert run(ctx, "mark_paid_by_customer") == {"error": "no_payment_requested"}
    run(ctx, "add_item", menu_item_id="nasi_lemak", qty=1)
    run(ctx, "set_order_type", type="pickup")
    run(ctx, "request_payment")
    r = run(ctx, "mark_paid_by_customer")
    assert r["ok"] and r["status"] == "payment_check"
    assert "payment.check_requested" in ctx.flags
    # the cart is now locked
    assert run(ctx, "add_item", menu_item_id="teh_tarik", qty=1)["error"] == "order_locked"


def test_handoff_and_ignore(ctx):
    assert run(ctx, "handoff_to_owner", reason="refund")["ok"]
    assert ctx.conversation.needs_owner and ctx.conversation.handoff_reason == "refund"
    assert run(ctx, "ignore_or_flag", reason="friend")["ignored"] is True
