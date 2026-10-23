from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=['pbkdf2_sha256'], deprecated='auto')


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(payload: dict | None = None, *, subject: str | None = None, user_id: str | None = None, role: str | None = None):
    """
    Backward-compatible token creator.

    Supported call styles:
    1) create_access_token(payload_dict) -> token (legacy tests)
    2) create_access_token(subject=..., user_id=..., role=...) -> (token, expires_at)
    """
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)

    if payload is not None:
        payload_data = dict(payload)
        payload_data.setdefault('exp', expires_at)
        token = jwt.encode(payload_data, settings.secret_key, algorithm=settings.algorithm)
        return token

    if subject is None or user_id is None or role is None:
        raise ValueError('Either payload or subject/user_id/role must be provided')

    payload = {
        'sub': subject,
        'uid': user_id,
        'role': role,
        'exp': expires_at,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm],options={'require':['exp','sub']})
    except InvalidTokenError as exc:
        raise ValueError('Invalid or expired token') from exc
