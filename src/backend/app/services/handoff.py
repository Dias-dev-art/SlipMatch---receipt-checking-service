"""When the AI stays silent in a chat, and how it comes back.

- handoff / fallback: `needs_owner` is set (AI silent) until the owner presses Resume AI,
  or by itself 24h after `handoff_at`.
- owner takeover: the owner replied from the dashboard chat, so the AI pauses while they talk:
  15 minutes after their last reply (`ai_paused_until`). Closing the chat panel, Resume AI or
  the customer's /start end it at once. Seen live: a 24h pause left the customer unanswered
  after the owner was done.
"""

from datetime import timedelta

from sqlmodel import Session, col, select

from app.models import Conversation
from app.models.base import utcnow

AUTO_RESUME_AFTER = timedelta(hours=24)
OWNER_TAKEOVER_PAUSE = timedelta(minutes=15)


def resume_ai(conversation: Conversation) -> None:
    conversation.needs_owner = False
    conversation.handoff_reason = None
    conversation.handoff_at = None
    conversation.ai_paused_until = None


def owner_took_over(conversation: Conversation) -> None:
    """The owner is answering by hand: the handoff is handled; the AI is back after the pause."""
    conversation.needs_owner = False
    conversation.handoff_reason = None
    conversation.handoff_at = None
    conversation.ai_paused_until = utcnow() + OWNER_TAKEOVER_PAUSE


def resume_stale(session: Session) -> list[Conversation]:
    """Handoffs nobody acted on for 24h go back to the AI. Caller commits."""
    stale = list(
        session.exec(
            select(Conversation)
            .where(
                col(Conversation.needs_owner).is_(True),
                col(Conversation.handoff_at) < utcnow() - AUTO_RESUME_AFTER,
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    for conversation in stale:
        resume_ai(conversation)
        session.add(conversation)
    return stale
