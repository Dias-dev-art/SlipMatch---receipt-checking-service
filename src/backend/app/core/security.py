import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

ALGORITHM = "HS256"

password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(subject: uuid.UUID, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    return jwt.encode({"sub": str(subject), "exp": expire}, settings.JWT_SECRET, ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


class TokenEncryptionError(Exception):
    """TOKEN_ENCRYPTION_KEY is missing or does not match the stored token."""


def _fernet() -> Fernet:
    if not settings.TOKEN_ENCRYPTION_KEY:
        raise TokenEncryptionError("TOKEN_ENCRYPTION_KEY is not set")
    try:
        return Fernet(settings.TOKEN_ENCRYPTION_KEY)
    except ValueError as exc:
        raise TokenEncryptionError("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt_token(token: str) -> str:
    """Per-business WhatsApp access tokens are stored encrypted."""
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise TokenEncryptionError("stored token cannot be decrypted with this key") from exc
