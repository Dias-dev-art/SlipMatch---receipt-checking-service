import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, Numeric
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def id_field() -> Any:
    return Field(default_factory=uuid.uuid4, primary_key=True)


def ts_field(*, nullable: bool = False, **kw: Any) -> Any:
    """timestamptz, always UTC."""
    if not nullable:
        kw.setdefault("default_factory", utcnow)
    return Field(sa_type=DateTime(timezone=True), nullable=nullable, **kw)


def money_field(default: Decimal | None = None, *, nullable: bool = False, **kw: Any) -> Any:
    """numeric(10,2) in MYR, never float."""
    return Field(default=default, sa_type=Numeric(10, 2), nullable=nullable, **kw)


def pg_enum(cls: type[StrEnum], name: str) -> Any:
    """Native Postgres enum storing the lowercase values."""
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])
