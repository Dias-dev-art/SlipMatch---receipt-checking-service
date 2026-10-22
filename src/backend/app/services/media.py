"""Uploaded payment QRs and downloaded customer screenshots, served at /media.

The DB stores the path (`/media/<business>/<file>`), not the full URL, so a new ngrok or hosting
URL (PUBLIC_BASE_URL) does not break old links.
"""

import uuid

from app.core.config import settings

IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def save(business_id: uuid.UUID, kind: str, ext: str, data: bytes) -> str:
    folder = settings.MEDIA_DIR / str(business_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{kind}-{uuid.uuid4().hex}.{ext}"
    (folder / name).write_bytes(data)
    return f"/media/{business_id}/{name}"


def absolute_url(path: str | None) -> str | None:
    """Full link for WhatsApp and the dashboard; other values (media ids, URLs) pass through."""
    if not path:
        return None
    if path.startswith("/media/"):
        return settings.PUBLIC_BASE_URL.rstrip("/") + path
    return path
