"""Expire orders whose 10-minute timer ran out. An asyncio loop in the FastAPI lifespan."""

import asyncio
import logging

from sqlmodel import Session

from app.core import db
from app.services import events, orders, templates
from app.services.notify import notify_customer

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 30

_MESSAGES = {
    orders.CancelReason.payment_timeout: templates.cancelled_payment_timeout,
    orders.CancelReason.owner_timeout: templates.cancelled_owner_timeout,
}


def expire_due_orders() -> int:
    """One pass. Returns how many orders were cancelled."""
    with Session(db.engine) as session:
        due = orders.due_orders(session)
        done = []
        for order in due:
            reason = orders.expire(session, order)
            notify_customer(session, order, _MESSAGES[reason](order), payload={"reason": reason})
            done.append((order.business_id, order.id))
        session.commit()
    for business_id, order_id in done:
        events.bus.publish(business_id, events.ORDER_UPDATED, order_id=order_id)
    if done:
        log.info("expired %d orders", len(done))
    return len(done)


async def run_forever(interval: float = INTERVAL_SECONDS) -> None:
    while True:
        try:
            await asyncio.to_thread(expire_due_orders)
        except Exception:  # keep the loop alive; the next pass retries
            log.exception("timer pass failed")
        await asyncio.sleep(interval)
