import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _clean_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        tag = " ".join(tag.split()).lower()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


Price = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
Name = Annotated[str, Field(min_length=1, max_length=120), AfterValidator(str.strip)]
Tags = Annotated[list[str], AfterValidator(_clean_tags)]


class MenuItemCreate(BaseModel):
    name: Name
    price: Price
    description: str = ""
    tags: Tags = []
    category: str | None = None
    is_available: bool = True


class MenuItemUpdate(BaseModel):
    """Partial update. The slug is not editable: it is the id the AI uses."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    price: Price | None = None
    description: str | None = None
    tags: Tags | None = None
    category: str | None = None
    is_available: bool | None = None
    sort_order: int | None = None


class AvailabilityUpdate(BaseModel):
    is_available: bool


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    price: Decimal
    description: str
    tags: list[str]
    category: str | None
    is_available: bool
    sort_order: int
