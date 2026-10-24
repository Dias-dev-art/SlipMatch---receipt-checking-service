from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.deps import CurrentBusiness, CurrentOwner, SessionDep
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Business, Owner
from app.schemas.auth import OwnerOut, OwnerWithBusiness, RegisterIn, Token
from app.schemas.business import business_out
from app.services.shops import unique_shop_code

router = APIRouter(prefix="/auth", tags=["auth"])


def _out(session: Session, owner: Owner, business: Business) -> OwnerWithBusiness:
    return OwnerWithBusiness(
        owner=OwnerOut.model_validate(owner), business=business_out(session, business)
    )


@router.post("/register", response_model=OwnerWithBusiness, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, session: SessionDep) -> OwnerWithBusiness:
    email = body.email.lower()
    if session.exec(select(Owner).where(Owner.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    owner = Owner(
        email=email, hashed_password=hash_password(body.password), full_name=body.full_name
    )
    business = Business(
        owner_id=owner.id,
        name=body.business_name,
        shop_code=unique_shop_code(session, body.business_name),
    )
    session.add(owner)
    session.flush()
    session.add(business)
    try:
        session.commit()
    except IntegrityError:  # two registrations with the same email (or shop code) at once
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
    session.refresh(owner)
    session.refresh(business)
    return _out(session, owner, business)


@router.post("/login", response_model=Token)
def login(session: SessionDep, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    owner = session.exec(select(Owner).where(Owner.email == form.username.lower())).first()
    if not owner or not verify_password(form.password, owner.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect email or password")
    if not owner.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Inactive owner")
    return Token(access_token=create_access_token(owner.id))


@router.get("/me", response_model=OwnerWithBusiness)
def me(session: SessionDep, owner: CurrentOwner, business: CurrentBusiness) -> OwnerWithBusiness:
    return _out(session, owner, business)
