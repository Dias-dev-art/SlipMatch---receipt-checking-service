"""Business settings. Always the owner's own business, taken from the token."""

import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.deps import CurrentBusiness, SessionDep
from app.core.security import TokenEncryptionError, encrypt_token
from app.models import ContactExclusion, WhatsAppAccount
from app.schemas.business import (
    BusinessOut,
    BusinessPatch,
    ExclusionIn,
    ExclusionOut,
    WhatsAppIn,
    business_out,
)
from app.services import media

router = APIRouter(prefix="/business", tags=["business"])

MAX_QR_BYTES = 2 * 1024 * 1024
_NOT_NULL = (
    "name",
    "delivery_enabled",
    "delivery_fee",
    "pickup_enabled",
    "payment_instructions",
    "unique_amount_cents",
    "payment_timeout_minutes",
)


@router.get("", response_model=BusinessOut)
def get_business(session: SessionDep, business: CurrentBusiness) -> BusinessOut:
    return business_out(session, business)


@router.patch("", response_model=BusinessOut)
def update_business(
    body: BusinessPatch, session: SessionDep, business: CurrentBusiness
) -> BusinessOut:
    changes = body.model_dump(exclude_unset=True)
    for field in _NOT_NULL:
        if field in changes and changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} cannot be null")
    if "greeting" in changes:
        changes["greeting"] = (changes["greeting"] or "").strip() or None
    for key, value in changes.items():
        setattr(business, key, value)
    if not business.pickup_enabled and not business.delivery_enabled:
        session.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Enable at least pickup or delivery"
        )
    session.add(business)
    session.commit()
    session.refresh(business)
    return business_out(session, business)


@router.post("/payment-qr", response_model=BusinessOut)
def upload_payment_qr(
    file: UploadFile, session: SessionDep, business: CurrentBusiness
) -> BusinessOut:
    """DuitNow QR image. Sent to the customer by link, so it is served publicly at /media."""
    ext = media.IMAGE_TYPES.get(file.content_type or "")
    if not ext:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a PNG, JPEG or WebP")
    data = file.file.read(MAX_QR_BYTES + 1)
    if len(data) > MAX_QR_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image must be 2 MB or smaller")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
    business.payment_qr_url = media.save(business.id, "qr", ext, data)
    session.add(business)
    session.commit()
    session.refresh(business)
    return business_out(session, business)


@router.put("/whatsapp", response_model=BusinessOut)
def connect_whatsapp(
    body: WhatsAppIn, session: SessionDep, business: CurrentBusiness
) -> BusinessOut:
    """Connect (or replace) the business's WhatsApp number. The token is stored encrypted."""
    try:
        encrypted = encrypt_token(body.access_token)
    except TokenEncryptionError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Server is missing TOKEN_ENCRYPTION_KEY"
        ) from None
    account = session.exec(
        select(WhatsAppAccount).where(WhatsAppAccount.business_id == business.id)
    ).first() or WhatsAppAccount(
        business_id=business.id, phone_number_id="", display_phone="", access_token_encrypted=""
    )
    account.phone_number_id = body.phone_number_id
    account.display_phone = body.display_phone
    account.access_token_encrypted = encrypted
    account.coexistence = body.coexistence
    session.add(account)
    try:
        session.commit()
    except IntegrityError:  # phone_number_id is unique across businesses
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This WhatsApp number is connected to another business"
        ) from None
    return business_out(session, business)


# ---------------------------------------------------------------- exclusions


@router.get("/exclusions", response_model=list[ExclusionOut])
def list_exclusions(session: SessionDep, business: CurrentBusiness) -> list[ContactExclusion]:
    return list(
        session.exec(
            select(ContactExclusion)
            .where(ContactExclusion.business_id == business.id)
            .order_by(col(ContactExclusion.label), col(ContactExclusion.wa_phone))
        ).all()
    )


@router.post("/exclusions", response_model=ExclusionOut, status_code=status.HTTP_201_CREATED)
def add_exclusion(
    body: ExclusionIn, session: SessionDep, business: CurrentBusiness
) -> ContactExclusion:
    """The AI never answers this number (friends, family, suppliers)."""
    exclusion = ContactExclusion(
        business_id=business.id, wa_phone=body.wa_phone, label=body.label.strip()
    )
    session.add(exclusion)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This number is already excluded") from None
    session.refresh(exclusion)
    return exclusion


@router.delete("/exclusions/{exclusion_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_exclusion(
    exclusion_id: uuid.UUID, session: SessionDep, business: CurrentBusiness
) -> None:
    exclusion = session.exec(
        select(ContactExclusion).where(
            ContactExclusion.id == exclusion_id, ContactExclusion.business_id == business.id
        )
    ).first()
    if not exclusion:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclusion not found")
    session.delete(exclusion)
    session.commit()
