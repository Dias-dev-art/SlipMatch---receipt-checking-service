from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlmodel import select

from app.core.deps import SessionDep
from app.core.security import decode_access_token
from app.models import Business, Owner
from app.services import events

router = APIRouter(tags=["realtime"])


def business_from_query_token(session: SessionDep, token: Annotated[str, Query()]) -> Business:
    """EventSource cannot set headers, so the JWT comes as ?token=."""
    owner_id = decode_access_token(token)
    owner = session.get(Owner, owner_id) if owner_id else None
    business = (
        session.exec(select(Business).where(Business.owner_id == owner.id)).first()
        if owner and owner.is_active
        else None
    )
    if not business:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Could not validate credentials")
    return business


@router.get("/events", response_class=StreamingResponse)
async def stream_events(
    business: Annotated[Business, Depends(business_from_query_token)],
) -> StreamingResponse:
    """SSE: order.created, order.updated, payment.check_requested, conversation.needs_owner."""
    sub = events.bus.subscribe(business.id)
    return StreamingResponse(
        events.stream(sub),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
