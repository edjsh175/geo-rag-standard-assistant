from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.auth import (
    UserIdentity,
    create_visitor_access_token,
    clear_auth_cookie,
    create_access_token,
    hash_client_ip,
    set_auth_cookie,
    validate_admin_auth_configuration,
    verify_admin_credentials,
)
from app.core.config import settings
from app.core.security import require_authenticated_user
from app.services.demo_quota_service import DemoQuotaService, DemoQuotaStatus, get_demo_quota_service

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthUserResponse(BaseModel):
    username: str
    role: str
    quota: DemoQuotaStatus | None = None


class LoginResponse(BaseModel):
    user: AuthUserResponse
    message: str


class DemoLoginResponse(BaseModel):
    user: AuthUserResponse
    quota: DemoQuotaStatus
    message: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response) -> LoginResponse:
    try:
        validate_admin_auth_configuration()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if not verify_admin_credentials(request.username, request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username or password is incorrect.",
        )

    token = create_access_token(request.username)
    set_auth_cookie(response, token)
    return LoginResponse(
        user=AuthUserResponse(username=request.username, role="admin"),
        message="Login successful.",
    )


@router.post("/demo", response_model=DemoLoginResponse)
async def demo_login(
    request: Request,
    response: Response,
    quota_service: DemoQuotaService = Depends(get_demo_quota_service),
) -> DemoLoginResponse:
    if not settings.PUBLIC_DEMO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public demo access is disabled.",
        )

    visitor_id = str(uuid.uuid4())
    token = create_visitor_access_token(visitor_id)
    set_auth_cookie(response, token)
    visitor_identity = UserIdentity(
        username="demo-visitor",
        role="visitor",
        visitor_id=visitor_id,
        ip_hash=hash_client_ip(request),
    )
    quota = await quota_service.get_status(
        visitor_identity.visitor_id or "",
        visitor_identity.ip_hash or "",
    )
    return DemoLoginResponse(
        user=AuthUserResponse(username=visitor_identity.username, role="visitor", quota=quota),
        quota=quota,
        message="Demo session started.",
    )


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_auth_cookie(response)
    return {"message": "Logged out."}


@router.get("/me", response_model=AuthUserResponse)
async def me(
    current_user: UserIdentity = Depends(require_authenticated_user),
    quota_service: DemoQuotaService = Depends(get_demo_quota_service),
) -> AuthUserResponse:
    quota = None
    if current_user.role == "visitor":
        quota = await quota_service.get_status(current_user.visitor_id or "", current_user.ip_hash or "")
    return AuthUserResponse(username=current_user.username, role=current_user.role, quota=quota)
