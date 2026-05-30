from secrets import compare_digest
from typing import Annotated

from fastapi import Header, HTTPException, Request, status

from app.core.auth import AdminIdentity, UserIdentity, get_authenticated_admin, get_authenticated_user
from app.core.config import settings


def require_system_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    expected_api_key = settings.SYSTEM_API_KEY
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System management API is not configured",
        )

    if not compare_digest(x_api_key, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return x_api_key


def require_admin_or_system_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    expected_api_key = settings.SYSTEM_API_KEY
    if x_api_key and expected_api_key and compare_digest(x_api_key, expected_api_key):
        return "system"

    try:
        admin = get_authenticated_admin(request)
    except HTTPException as admin_exc:
        if x_api_key:
            detail = "Invalid API key" if expected_api_key else "System management API is not configured"
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail) from admin_exc
        raise

    return admin.username


def require_clear_cache_confirmation(
    x_confirm_action: Annotated[str | None, Header(alias="X-Confirm-Action")] = None,
) -> str:
    expected_confirmation = settings.SYSTEM_CLEAR_CACHE_CONFIRM_VALUE
    if not x_confirm_action or not compare_digest(x_confirm_action, expected_confirmation):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing or invalid X-Confirm-Action header. Expected '{expected_confirmation}'.",
        )

    return x_confirm_action


def require_authenticated_admin(request: Request) -> AdminIdentity:
    return get_authenticated_admin(request)


def require_authenticated_user(request: Request) -> UserIdentity:
    return get_authenticated_user(request)
