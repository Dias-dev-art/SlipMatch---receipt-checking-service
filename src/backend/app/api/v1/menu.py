import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from app.core.deps import CurrentBusiness, SessionDep
from app.models import MenuItem, OrderItem
from app.models.base import utcnow
from app.schemas.menu import AvailabilityUpdate, MenuItemCreate, MenuItemOut, MenuItemUpdate
from app.services import menu as menu_service

router = APIRouter(prefix="/menu", tags=["menu"])


def _get_or_404(session: SessionDep, business: CurrentBusiness, item_id: uuid.UUID) -> MenuItem:
    item = menu_service.get_item(session, business.id, item_id)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Menu item not found")
    return item


@router.get("", response_model=list[MenuItemOut])
def list_menu(session: SessionDep, business: CurrentBusiness) -> list[MenuItem]:
    return list(
        session.exec(
            select(MenuItem)
            .where(MenuItem.business_id == business.id, col(MenuItem.deleted_at).is_(None))
            .order_by(col(MenuItem.sort_order), col(MenuItem.name))
        ).all()
    )


@router.post("", response_model=MenuItemOut, status_code=status.HTTP_201_CREATED)
def create_item(body: MenuItemCreate, session: SessionDep, business: CurrentBusiness) -> MenuItem:
    item = MenuItem(
        business_id=business.id,
        slug=menu_service.unique_slug(session, business.id, body.name),
        sort_order=menu_service.next_sort_order(session, business.id),
        **body.model_dump(),
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError:  # same name created twice at the same moment
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Item with this name already exists"
        ) from None
    session.refresh(item)
    return item


@router.patch("/{item_id}", response_model=MenuItemOut)
def update_item(
    item_id: uuid.UUID, body: MenuItemUpdate, session: SessionDep, business: CurrentBusiness
) -> MenuItem:
    item = _get_or_404(session, business, item_id)
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "price", "tags", "is_available", "sort_order", "description"):
        if field in changes and changes[field] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{field} cannot be null")
    for key, value in changes.items():
        setattr(item, key, value)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.patch("/{item_id}/availability", response_model=MenuItemOut)
def set_availability(
    item_id: uuid.UUID, body: AvailabilityUpdate, session: SessionDep, business: CurrentBusiness
) -> MenuItem:
    """Quick sold-out toggle. The AI stops offering the item on the next message."""
    item = _get_or_404(session, business, item_id)
    item.is_available = body.is_available
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: uuid.UUID, session: SessionDep, business: CurrentBusiness) -> None:
    item = _get_or_404(session, business, item_id)
    used = session.exec(select(OrderItem.id).where(OrderItem.menu_item_id == item.id)).first()
    if used:
        # orders keep pointing at it; it just disappears from the menu and from the AI
        item.deleted_at = utcnow()
        item.is_available = False
        session.add(item)
    else:
        session.delete(item)
    session.commit()
