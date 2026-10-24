"""Uploaded payment QRs and downloaded customer screenshots, served at /media.

Stored in Postgres (`media_files`): hosting disks are wiped on every deploy. The DB stores the
path (`/media/<business>/<file>`), not the full URL, so a new ngrok or hosting URL
(PUBLIC_BASE_URL) does not break old links. Telegram gets the bytes uploaded, never the link.
"""

import uuid

from sqlmodel import Session, select

from app.core.config import settings
from app.models import MediaFile

IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_CONTENT_TYPES = {ext: mime for mime, ext in IMAGE_TYPES.items()}


def save(session: Session, business_id: uuid.UUID, kind: str, ext: str, data: bytes) -> str:
    """Adds the file to the session; it is stored with the caller's commit."""
    path = f"/media/{business_id}/{kind}-{uuid.uuid4().hex}.{ext}"
    session.add(
        MediaFile(business_id=business_id, path=path, content_type=_CONTENT_TYPES[ext], data=data)
    )
    session.flush()
    return path


def load(session: Session, path: str) -> MediaFile | None:
    return session.exec(select(MediaFile).where(MediaFile.path == path)).first()


def absolute_url(path: str | None) -> str | None:
    """Full link for the dashboard; other values (file ids, URLs) pass through."""
    if not path:
        return None
    if path.startswith("/media/"):
        return settings.PUBLIC_BASE_URL.rstrip("/") + path
    return path


def path_of(url: str) -> str | None:
    """Back from `absolute_url()`: the /media/... path, or None for any other link."""
    path = url.removeprefix(settings.PUBLIC_BASE_URL.rstrip("/"))
    return path if path.startswith("/media/") else None
