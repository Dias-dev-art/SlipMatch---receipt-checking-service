"""Chats the AI handed to the owner: the owner reads and answers them here, or presses Resume AI."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.core.deps import CurrentBusiness, SessionDep
from app.models import Business, Conversation, Customer, Direction, Message, MessageType, Sender
from app.schemas.order import CustomerOut, customer_out
from app.services import handoff, templates
from app.services.outbox import get_outbox

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    id: uuid.UUID
    customer: CustomerOut
    needs_owner: bool
    handoff_reason: str | None
    handoff_at: datetime | None
    ai_paused_until: datetime | None
    last_customer_message_at: datetime
    last_message: str | None
    created_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    direction: Direction
    sender: Sender
    type: MessageType
    body: str | None
    created_at: datetime


def _out(session: Session, conversation: Conversation) -> ConversationOut:
    customer = session.get(Customer, conversation.customer_id)
    last = session.exec(
        select(Message.body)
        .where(Message.conversation_id == conversation.id, col(Message.body).is_not(None))
        .order_by(col(Message.created_at).desc())
    ).first()
    return ConversationOut(
        id=conversation.id,
        customer=customer_out(customer),
        needs_owner=conversation.needs_owner,
        handoff_reason=conversation.handoff_reason,
        handoff_at=conversation.handoff_at,
        ai_paused_until=conversation.ai_paused_until,
        last_customer_message_at=conversation.last_customer_message_at,
        last_message=last,
        created_at=conversation.created_at,
    )


def _get_or_404(
    session: Session, business: Business, conversation_id: uuid.UUID, *, lock: bool = False
) -> Conversation:
    query = select(Conversation).where(
        Conversation.id == conversation_id, Conversation.business_id == business.id
    )
    conversation = session.exec(query.with_for_update() if lock else query).first()
    if not conversation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    session: SessionDep,
    business: CurrentBusiness,
    needs_owner: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ConversationOut]:
    """Most recent first. `?needs_owner=true`: the chats the AI handed off."""
    query = select(Conversation).where(Conversation.business_id == business.id)
    if needs_owner is not None:
        query = query.where(Conversation.needs_owner == needs_owner)
    query = query.order_by(col(Conversation.last_customer_message_at).desc()).limit(limit)
    return [_out(session, c) for c in session.exec(query).all()]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: uuid.UUID,
    session: SessionDep,
    business: CurrentBusiness,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Message]:
    """The last `limit` messages, oldest first."""
    conversation = _get_or_404(session, business, conversation_id)
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(col(Message.created_at).desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


@router.post("/{conversation_id}/resume-ai", response_model=ConversationOut)
def resume_ai(
    conversation_id: uuid.UUID, session: SessionDep, business: CurrentBusiness
) -> ConversationOut:
    """Clear the handoff flag and any owner-takeover pause; the AI answers the next message."""
    conversation = _get_or_404(session, business, conversation_id, lock=True)
    handoff.resume_ai(conversation)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return _out(session, conversation)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/{conversation_id}/reply", response_model=ConversationOut)
def reply(
    conversation_id: uuid.UUID, body: ReplyIn, session: SessionDep, business: CurrentBusiness
) -> ConversationOut:
    """The owner answers the customer: sent through the bot, signed with the shop's name.

    The owner now has the chat, so the AI stays silent for 15 minutes after this reply (the
    dashboard resumes it at once when the owner closes the chat panel).
    """
    conversation = _get_or_404(session, business, conversation_id, lock=True)
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The message is empty")
    customer = session.get(Customer, conversation.customer_id)
    sent = templates.owner_reply(business, text)
    get_outbox(session, business.id).send_text(customer.tg_chat_id, sent)
    session.add(
        Message(
            business_id=business.id,
            conversation_id=conversation.id,
            direction=Direction.out,
            sender=Sender.owner,
            body=sent,
        )
    )
    handoff.owner_took_over(conversation)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return _out(session, conversation)
