"""Expire orders whose 10-minute timer ran out, and give stale handoffs back to the AI.

An asyncio loop in the FastAPI lifespan.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete
from sqlmodel import Session, col

from app.core import db
from app.models import ProcessedWebhook
from app.models.base import utcnow
from app.services import events, handoff, orders, templates
from app.services.notify import notify_customer

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 30
WEBHOOK_MEMORY = timedelta(days=7)

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


def resume_stale_handoffs() -> int:
    """One pass. Handoffs nobody acted on for 24h: the AI answers again."""
    with Session(db.engine) as session:
        resumed = handoff.resume_stale(session)
        session.commit()
    if resumed:
        log.info("auto-resumed AI in %d conversations", len(resumed))
    return len(resumed)


def forget_old_webhooks() -> int:
    """Meta stops retrying long before 7 days, so old message ids can go."""
    with Session(db.engine) as session:
        removed = session.exec(
            delete(ProcessedWebhook)
            .where(col(ProcessedWebhook.received_at) < utcnow() - WEBHOOK_MEMORY)
            .returning(ProcessedWebhook.wa_message_id)
        ).all()
        session.commit()
    return len(removed)


async def run_forever(interval: float = INTERVAL_SECONDS) -> None:
    while True:
        for job in (expire_due_orders, resume_stale_handoffs, forget_old_webhooks):
            try:
                await asyncio.to_thread(job)
            except Exception:  # keep the loop alive; the next pass retries
                log.exception("timer pass failed: %s", job.__name__)
        await asyncio.sleep(interval)
