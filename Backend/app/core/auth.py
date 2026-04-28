from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import compare_digest

from fastapi import HTTPException, Request, Response, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass(frozen=True)
class AdminIdentity:
    username: str
    role: str = "admin"


def validate_admin_auth_configuration() -> None:
    if not settings.ADMIN_USERNAME:
        raise RuntimeError("ADMIN_USERNAME is not configured.")
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not configured.")
    if not settings.ADMIN_PASSWORD_HASH and not settings.ADMIN_PASSWORD:
        raise RuntimeError("Either ADMIN_PASSWORD_HASH or ADMIN_PASSWORD must be configured.")
    if settings.ADMIN_PASSWORD_HASH:
        if not pwd_context.identify(settings.ADMIN_PASSWORD_HASH):
            raise RuntimeError("ADMIN_PASSWORD_HASH is invalid.")


def verify_admin_credentials(username: str, password: str) -> bool:
    configured_username = settings.ADMIN_USERNAME or ""
    if not configured_username or not compare_digest(username, configured_username):
        return False

    if settings.ADMIN_PASSWORD_HASH:
        return pwd_context.verify(password, settings.ADMIN_PASSWORD_HASH)

    configured_password = settings.ADMIN_PASSWORD or ""
    return compare_digest(password, configured_password)


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,
        "role": "admin",
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, str]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def should_use_secure_cookie() -> bool:
    return settings.AUTH_COOKIE_SECURE and not settings.DEBUG


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=should_use_secure_cookie(),
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        httponly=True,
        secure=should_use_secure_cookie(),
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )


def get_authenticated_admin(request: Request) -> AdminIdentity:
    validate_admin_auth_configuration()

    token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is invalid or expired.",
        ) from exc

    username = payload.get("sub") or ""
    if not settings.ADMIN_USERNAME or not compare_digest(username, settings.ADMIN_USERNAME):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session user is not allowed.",
        )

    return AdminIdentity(username=username)
