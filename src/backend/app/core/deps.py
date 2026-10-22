from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models import Business, Owner

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

SessionDep = Annotated[Session, Depends(get_session)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]


def get_current_owner(session: SessionDep, token: TokenDep) -> Owner:
    owner_id = decode_access_token(token)
    owner = session.get(Owner, owner_id) if owner_id else None
    if not owner or not owner.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return owner


CurrentOwner = Annotated[Owner, Depends(get_current_owner)]


def get_current_business(session: SessionDep, owner: CurrentOwner) -> Business:
    """The tenant of every dashboard request. Never taken from the request body."""
    business = session.exec(select(Business).where(Business.owner_id == owner.id)).first()
    if not business:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business


CurrentBusiness = Annotated[Business, Depends(get_current_business)]
