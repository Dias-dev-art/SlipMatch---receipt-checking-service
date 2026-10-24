"""execute_tool(): validates every LLM tool call against the DB and returns JSON for the LLM.

Never trusts LLM numbers: prices come from the DB, totals are Decimal, ids are slugs looked up
with business_id. Errors are normal results the LLM must react to.
"""

import difflib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session, col, select

from app.models import (
    Business,
    Conversation,
    Customer,
    MenuItem,
    Order,
    OrderItem,
    OrderStatus,
    OrderType,
)
from app.models.base import utcnow
from app.services import media, orders, templates

log = logging.getLogger(__name__)

MAX_QTY = 99
MAX_TEXT = 500


@dataclass
class ToolContext:
    session: Session
    business: Business
    conversation: Conversation
    send_text: Callable[[str], None]
    send_image: Callable[[str, str | None], None]
    # sends the text with Telegram's "Share phone number" button; None = no phone needed
    ask_phone: Callable[[str], None] | None = None
    handoff: bool = False
    ignored: bool = False
    flags: list[str] = field(default_factory=list)

    @property
    def order(self) -> Order | None:
        return orders.get_active_order(self.session, self.conversation.id)


def _money(value) -> float:
    return float(value)


def cart_result(ctx: ToolContext, order: Order, **extra: Any) -> dict[str, Any]:
    lines = orders.cart_lines(ctx.session, order)
    result = {
        "ok": True,
        "cart": [
            {
                "id": ln.slug,
                "name": ln.item.name_snapshot,
                "qty": ln.item.qty,
                "unit_price": _money(ln.item.unit_price_snapshot),
                **({"note": ln.item.note} if ln.item.note else {}),
            }
            for ln in lines
        ],
        "subtotal": _money(order.subtotal),
        "total": _money(order.total),
        "missing_fields": orders.missing_fields(ctx.session, order),
    }
    if order.order_type:
        result["order_type"] = order.order_type.value
    if order.delivery_fee:
        result["delivery_fee"] = _money(order.delivery_fee)
    return result | extra


def _menu_lookup(ctx: ToolContext, slug: str, *, include_deleted: bool = False) -> MenuItem | None:
    query = select(MenuItem).where(MenuItem.business_id == ctx.business.id, MenuItem.slug == slug)
    if not include_deleted:
        query = query.where(col(MenuItem.deleted_at).is_(None))
    return ctx.session.exec(query).first()


def _suggestions(ctx: ToolContext, wanted: str) -> list[str]:
    items = ctx.session.exec(
        select(MenuItem).where(
            MenuItem.business_id == ctx.business.id,
            col(MenuItem.is_available).is_(True),
            col(MenuItem.deleted_at).is_(None),
        )
    ).all()
    by_key = {i.slug: i.slug for i in items} | {i.name.lower(): i.slug for i in items}
    close = difflib.get_close_matches(wanted.lower(), list(by_key), n=3, cutoff=0.4)
    seen: list[str] = []
    for key in close:
        if by_key[key] not in seen:
            seen.append(by_key[key])
    return seen


def _editable_order(ctx: ToolContext, *, create: bool) -> tuple[Order | None, dict | None, bool]:
    """Active order the cart may change on. Returns (order, error, payment_request_cancelled)."""
    order = ctx.order
    if order is None:
        if not create:
            return None, {"error": "no_active_order"}, False
        return orders.create_order(ctx.session, ctx.conversation), None, False
    if order.status == OrderStatus.payment_check:
        return None, {"error": "order_locked", "status": order.status.value}, False
    if order.status == OrderStatus.awaiting_payment:
        # the cart is locked once payment is requested; changing it cancels the request
        orders.reopen_for_changes(ctx.session, order)
        return order, None, True
    return order, None, False


def _qty(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:MAX_TEXT] or None


# ---------------------------------------------------------------- tools


def add_item(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    slug = args.get("menu_item_id")
    qty = _qty(args.get("qty"))
    if not isinstance(slug, str) or not slug.strip():
        return {"error": "invalid_arguments", "detail": "menu_item_id is required"}
    if qty is None or qty < 1:
        return {"error": "invalid_arguments", "detail": "qty must be a whole number >= 1"}
    if qty > MAX_QTY:
        return {"error": "qty_too_large", "max": MAX_QTY}
    slug = slug.strip()
    item = _menu_lookup(ctx, slug)
    if item is None:
        return {"error": "not_on_menu", "item": slug, "suggestions": _suggestions(ctx, slug)}
    if not item.is_available:
        return {"error": "sold_out", "item": slug}

    order, error, reopened = _editable_order(ctx, create=True)
    if error:
        return error
    note = _text(args.get("note"))
    line = ctx.session.exec(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.menu_item_id == item.id,
            OrderItem.note == note if note else col(OrderItem.note).is_(None),
        )
    ).first()
    if line:
        if line.qty + qty > MAX_QTY:
            return {"error": "qty_too_large", "max": MAX_QTY}
        line.qty += qty
    else:
        line = OrderItem(
            order_id=order.id,
            menu_item_id=item.id,
            name_snapshot=item.name,
            unit_price_snapshot=item.price,  # price from the DB, never from the LLM
            qty=qty,
            note=note,
        )
    ctx.session.add(line)
    orders.recalc(ctx.session, order)
    extra = {"payment_request_cancelled": True} if reopened else {}
    return cart_result(ctx, order, **extra)


def remove_item(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    slug = args.get("menu_item_id")
    if not isinstance(slug, str) or not slug.strip():
        return {"error": "invalid_arguments", "detail": "menu_item_id is required"}
    qty = None
    if args.get("qty") is not None:
        qty = _qty(args["qty"])
        if qty is None or qty < 1:
            return {"error": "invalid_arguments", "detail": "qty must be a whole number >= 1"}
    order, error, reopened = _editable_order(ctx, create=False)
    if error:
        return error
    item = _menu_lookup(ctx, slug.strip(), include_deleted=True)
    lines = (
        ctx.session.exec(
            select(OrderItem)
            .where(OrderItem.order_id == order.id, OrderItem.menu_item_id == item.id)
            .order_by(col(OrderItem.id).desc())
        ).all()
        if item
        else []
    )
    if not lines:
        return {"error": "not_in_cart", "item": slug}
    remaining = qty if qty is not None else sum(ln.qty for ln in lines)
    for ln in lines:
        if remaining <= 0:
            break
        take = min(ln.qty, remaining)
        ln.qty -= take
        remaining -= take
        if ln.qty == 0:
            ctx.session.delete(ln)
        else:
            ctx.session.add(ln)
    orders.recalc(ctx.session, order)
    extra = {"payment_request_cancelled": True} if reopened else {}
    return cart_result(ctx, order, **extra)


def set_order_type(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        order_type = OrderType(args.get("type"))
    except ValueError:
        return {"error": "invalid_arguments", "detail": "type must be pickup or delivery"}
    if order_type == OrderType.delivery and not ctx.business.delivery_enabled:
        return {"error": "delivery_not_available"}
    if order_type == OrderType.pickup and not ctx.business.pickup_enabled:
        return {"error": "pickup_not_available"}
    order, error, reopened = _editable_order(ctx, create=True)
    if error:
        return error
    orders.set_order_type(order, ctx.business, order_type)
    orders.recalc(ctx.session, order)
    extra = {"payment_request_cancelled": True} if reopened else {}
    return cart_result(ctx, order, **extra)


def set_address(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    address = _text(args.get("address"))
    if not address:
        return {"error": "invalid_arguments", "detail": "address is required"}
    order, error, reopened = _editable_order(ctx, create=True)
    if error:
        return error
    order.address_text = address
    orders.recalc(ctx.session, order)
    extra = {"payment_request_cancelled": True} if reopened else {}
    return cart_result(ctx, order, **extra)


def request_payment(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    order = ctx.order
    if order is None:
        return {"error": "missing_fields", "fields": orders.missing_fields(ctx.session, None)}
    if order.status != OrderStatus.chatting:
        # already requested: do not send the QR twice
        return {
            "ok": True,
            "status": order.status.value,
            "code": order.code,
            "total": _money(order.total),
            "payment_sent": False,
        }
    missing = orders.missing_fields(ctx.session, order)
    if missing:
        return {"error": "missing_fields", "fields": missing}
    customer = ctx.session.get(Customer, ctx.conversation.customer_id)
    if ctx.ask_phone is not None and not customer.phone:
        # the payment details go out once the customer taps "Share phone number"
        ctx.ask_phone(templates.phone_request(order, orders.cart_lines(ctx.session, order)))
        return {
            "error": "phone_needed",
            "note": "A button to share the phone number was sent. Ask the customer to tap it.",
        }
    try:
        orders.request_payment(ctx.session, order, ctx.business)
    except orders.MissingFields as exc:
        return {"error": "missing_fields", "fields": exc.fields}
    if ctx.business.payment_qr_url:
        ctx.send_image(media.absolute_url(ctx.business.payment_qr_url), None)
    ctx.send_text(templates.payment_request(order, ctx.business))
    return {
        "ok": True,
        "status": order.status.value,
        "code": order.code,
        "total": _money(order.total),
        "payment_sent": True,
    }


def resend_payment_details(ctx: ToolContext) -> dict[str, Any]:
    """The customer asks for the QR again. Not an LLM tool: only code calls it."""
    order = ctx.order
    if order is None or order.status != OrderStatus.awaiting_payment:
        return {"error": "no_payment_requested"}
    if ctx.business.payment_qr_url:
        ctx.send_image(media.absolute_url(ctx.business.payment_qr_url), None)
    ctx.send_text(templates.payment_request(order, ctx.business))
    return {
        "ok": True,
        "status": order.status.value,
        "code": order.code,
        "total": _money(order.total),
        "payment_sent": True,
    }


def mark_paid_by_customer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    order = ctx.order
    if order is None or order.status == OrderStatus.chatting:
        return {"error": "no_payment_requested"}
    if order.status == OrderStatus.awaiting_payment:
        orders.mark_paid_by_customer(ctx.session, order, ctx.business)
        ctx.flags.append("payment.check_requested")
    return {
        "ok": True,
        "status": order.status.value,
        "code": order.code,
        "note": "The owner will check the bank. Do not say the payment is confirmed.",
    }


def handoff_to_owner(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    reason = _text(args.get("reason")) or "no reason given"
    ctx.conversation.needs_owner = True
    ctx.conversation.handoff_reason = reason
    ctx.conversation.handoff_at = utcnow()
    ctx.session.add(ctx.conversation)
    ctx.handoff = True
    ctx.flags.append("conversation.needs_owner")
    return {"ok": True, "handoff": True}


def ignore_or_flag(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    ctx.ignored = True
    return {"ok": True, "ignored": True, "reason": _text(args.get("reason"))}


HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], dict[str, Any]]] = {
    "add_item": add_item,
    "remove_item": remove_item,
    "set_order_type": set_order_type,
    "set_address": set_address,
    "request_payment": request_payment,
    "mark_paid_by_customer": mark_paid_by_customer,
    "handoff_to_owner": handoff_to_owner,
    "ignore_or_flag": ignore_or_flag,
}


def execute_tool(ctx: ToolContext, name: str, arguments: str | dict | None) -> dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": "unknown_tool", "tool": name}
    if isinstance(arguments, dict):
        args = arguments
    else:
        try:
            args = json.loads(arguments or "{}")
        except ValueError:
            return {"error": "invalid_arguments", "detail": "arguments are not valid JSON"}
    if not isinstance(args, dict):
        return {"error": "invalid_arguments", "detail": "arguments must be an object"}
    try:
        with ctx.session.begin_nested():  # a failing tool never leaves half-written rows
            return handler(ctx, args)
    except orders.OrderError as exc:
        return {"error": "invalid_state", "detail": str(exc)}
