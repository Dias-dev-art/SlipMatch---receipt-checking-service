"""Business settings. Always the owner's own business, taken from the token."""

from fastapi import APIRouter, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentBusiness, SessionDep
from app.schemas.business import BusinessOut, BusinessPatch, business_out
from app.services import media

router = APIRouter(prefix="/business", tags=["business"])

MAX_QR_BYTES = 2 * 1024 * 1024
_NOT_NULL = (
    "name",
    "shop_code",
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
    try:
        session.commit()
    except IntegrityError:  # shop_code is unique across businesses
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This shop code is taken by another business"
        ) from None
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
    business.payment_qr_url = media.save(session, business.id, "qr", ext, data)
    session.add(business)
    session.commit()
    session.refresh(business)
    return business_out(session, business)
