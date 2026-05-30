from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

import pytest

from app.api.auth_routes import demo_login
from app.core import auth
from app.core.config import settings
from app.core.security import require_admin_or_system_api_key
from app.services.demo_quota_service import DemoQuotaStatus


def make_request(cookie: str | None = None, host: str = "203.0.113.10") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (host, 12345),
        }
    )


class DemoQuotaStub:
    def __init__(self) -> None:
        self.status = DemoQuotaStatus(
            remaining=10,
            daily_limit=10,
            global_remaining=300,
            reset_at="2026-05-31T00:00:00+08:00",
            exhausted=False,
            contact_text="请联系项目作者获取更多演示额度。",
        )

    async def get_status(self, visitor_id: str, ip_hash: str) -> DemoQuotaStatus:
        assert visitor_id
        assert ip_hash
        return self.status


@pytest.mark.asyncio
async def test_demo_login_creates_visitor_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_DEMO_ENABLED", True)
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(settings, "AUTH_COOKIE_NAME", "geoai_session")

    response = Response()
    payload = await demo_login(
        request=make_request(),
        response=response,
        quota_service=DemoQuotaStub(),
    )

    assert payload.user.role == "visitor"
    assert payload.user.username == "demo-visitor"
    assert payload.quota.remaining == 10
    assert "geoai_session=" in response.headers["set-cookie"]

    cookie_value = response.headers["set-cookie"].split("geoai_session=", 1)[1].split(";", 1)[0]
    identity = auth.get_authenticated_user(make_request(cookie=f"geoai_session={cookie_value}"))
    assert identity.role == "visitor"
    assert identity.visitor_id
    assert identity.username == "demo-visitor"


@pytest.mark.asyncio
async def test_demo_login_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_DEMO_ENABLED", False)

    with pytest.raises(Exception) as exc_info:
        await demo_login(
            request=make_request(),
            response=Response(),
            quota_service=DemoQuotaStub(),
        )

    assert getattr(exc_info.value, "status_code", None) == 403


def test_management_auth_allows_system_api_key_without_admin_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SYSTEM_API_KEY", "system-key")

    identity = require_admin_or_system_api_key(make_request(), x_api_key="system-key")

    assert identity == "system"


def test_management_auth_allows_admin_without_system_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "admin-password")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", "")
    monkeypatch.setattr(settings, "AUTH_COOKIE_NAME", "geoai_session")

    token = auth.create_access_token("admin")
    identity = require_admin_or_system_api_key(
        make_request(cookie=f"geoai_session={token}"),
        x_api_key=None,
    )

    assert identity == "admin"
