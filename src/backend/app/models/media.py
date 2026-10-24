import uuid
from datetime import datetime

from sqlalchemy import LargeBinary
from sqlmodel import Field, SQLModel

from app.models.base import id_field, ts_field


class MediaFile(SQLModel, table=True):
    """Payment QRs and customer screenshots. In the DB because hosting disks are wiped on deploy."""

    __tablename__ = "media_files"

    id: uuid.UUID = id_field()
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    # the public link path, `/media/<business>/<file>`
    path: str = Field(unique=True)
    content_type: str
    data: bytes = Field(sa_type=LargeBinary)
    created_at: datetime = ts_field()
