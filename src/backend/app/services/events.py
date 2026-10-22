"""In-process pub/sub for SSE, per business. Fine for one backend process (hackathon)."""

import asyncio
import json
import logging
import threading
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

ORDER_CREATED = "order.created"
ORDER_UPDATED = "order.updated"
PAYMENT_CHECK_REQUESTED = "payment.check_requested"
CONVERSATION_NEEDS_OWNER = "conversation.needs_owner"

HEARTBEAT_SECONDS = 15


@dataclass(frozen=True)
class Event:
    type: str
    data: dict[str, str]

    def sse(self) -> str:
        return f"event: {self.type}\ndata: {json.dumps(self.data)}\n\n"


@dataclass(eq=False)
class Subscriber:
    business_id: uuid.UUID
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[Event] = field(default_factory=lambda: asyncio.Queue(maxsize=100))

    def _put(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:  # slow client: drop, it re-fetches on the next event
            log.warning("SSE queue full, event dropped")


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[Subscriber]] = {}
        self._lock = threading.Lock()

    def subscribe(self, business_id: uuid.UUID) -> Subscriber:
        sub = Subscriber(business_id, asyncio.get_running_loop())
        with self._lock:
            self._subs.setdefault(business_id, set()).add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            self._subs.get(sub.business_id, set()).discard(sub)

    def publish(self, business_id: uuid.UUID, type_: str, **data: uuid.UUID | str) -> None:
        """Safe to call from sync code in worker threads. Call after the DB commit."""
        event = Event(type_, {k: str(v) for k, v in data.items()})
        with self._lock:
            subs = list(self._subs.get(business_id, ()))
        for sub in subs:
            sub.loop.call_soon_threadsafe(sub._put, event)


bus = EventBus()


async def stream(sub: Subscriber, heartbeat: float = HEARTBEAT_SECONDS) -> AsyncIterator[str]:
    try:
        yield ": connected\n\n"
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), heartbeat)
            except TimeoutError:
                yield ": ping\n\n"  # keeps proxies from closing the connection
                continue
            yield event.sse()
    finally:
        bus.unsubscribe(sub)
