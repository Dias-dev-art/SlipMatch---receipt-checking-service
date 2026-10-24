"""Public /media links: payment QRs and customer payment screenshots, shown in the dashboard."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.core.deps import SessionDep
from app.services import media

router = APIRouter(tags=["media"])


@router.get("/media/{business_id}/{name}")
def get_media(business_id: uuid.UUID, name: str, session: SessionDep) -> Response:
    file = media.load(session, f"/media/{business_id}/{name}")
    if file is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    # names are random and never reused, so the content never changes
    return Response(
        file.data,
        media_type=file.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
