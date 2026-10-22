import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

from app.models.base import id_field, money_field, ts_field


class MenuItem(SQLModel, table=True):
    __tablename__ = "menu_items"
    __table_args__ = (UniqueConstraint("business_id", "slug", name="uq_menu_items_business_slug"),)

    id: uuid.UUID = id_field()
    business_id: uuid.UUID = Field(foreign_key="businesses.id", index=True)
    # stable id shown to the LLM, e.g. `mee_goreng`; never changes on rename
    slug: str
    name: str
    price: Decimal = money_field()
    # ingredients, what's in it; the AI answers questions only from this
    description: str = ""
    tags: list[str] = Field(default_factory=list, sa_column=Column(ARRAY(String), nullable=False))
    category: str | None = None
    is_available: bool = True
    sort_order: int = 0
    # soft delete when referenced by orders (not in DATABASE.md, agreed with the team)
    deleted_at: datetime | None = ts_field(nullable=True, default=None)
