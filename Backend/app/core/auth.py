from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import uuid
from secrets import compare_digest
from typing import Optional

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


@dataclass(frozen=True)
class UserIdentity:
    username: str
    role: str = "admin"
    visitor_id: Optional[str] = None
    ip_hash: Optional[str] = None


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


def create_visitor_access_token(visitor_id: Optional[str] = None) -> str:
    subject = visitor_id or str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    payload = {
        "sub": "demo-visitor",
        "role": "visitor",
        "visitor_id": subject,
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


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def hash_client_ip(request: Request) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        get_client_ip(request).encode("utf-8"),
        digestmod="sha256",
    ).hexdigest()


def get_authenticated_user(request: Request) -> UserIdentity:
    if not settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SECRET_KEY is not configured.",
        )

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
    role = payload.get("role") or "admin"

    if role == "visitor":
        visitor_id = payload.get("visitor_id") or ""
        if not visitor_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Visitor session is invalid.",
            )
        return UserIdentity(
            username="demo-visitor",
            role="visitor",
            visitor_id=visitor_id,
            ip_hash=hash_client_ip(request),
        )

    if role != "admin" or not settings.ADMIN_USERNAME or not compare_digest(username, settings.ADMIN_USERNAME):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session user is not allowed.",
        )

    return UserIdentity(username=username, role="admin")


def get_authenticated_admin(request: Request) -> AdminIdentity:
    validate_admin_auth_configuration()
    identity = get_authenticated_user(request)
    if identity.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return AdminIdentity(username=identity.username)
