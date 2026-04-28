from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.auth import (
    AdminIdentity,
    clear_auth_cookie,
    create_access_token,
    set_auth_cookie,
    validate_admin_auth_configuration,
    verify_admin_credentials,
)
from app.core.security import require_authenticated_admin

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthUserResponse(BaseModel):
    username: str
    role: str


class LoginResponse(BaseModel):
    user: AuthUserResponse
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


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    clear_auth_cookie(response)
    return {"message": "Logged out."}


@router.get("/me", response_model=AuthUserResponse)
async def me(
    current_admin: AdminIdentity = Depends(require_authenticated_admin),
) -> AuthUserResponse:
    return AuthUserResponse(username=current_admin.username, role=current_admin.role)
